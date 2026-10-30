"""R-233：DeepSeek 网页搜索 / 抓取薄客户端。

官方文档：https://api-docs.deepseek.com/zh-cn/guides/search

- `POST /v1/tools/search`：搜索网页；`need_content=true` 时 `content` 直接带正文
  （实测知乎等反爬站点也能拿到 1.5k~3k 字，比单独 Fetch 稳）。
- `POST /v1/tools/fetch`：抓单个网页的 Markdown 正文（部分站点反爬会 404）。

约束：
- 未配置 `ECHO_DEEPSEEK_API_KEY` 或 `ECHO_DEEPSEEK_SEARCH_ENABLED=0` → `enabled()` False，
  `search()` / `fetch()` 直接返回空（静默降级，不阻断生成）。
- 账号级 Search / Fetch 各 5 QPS：进程内限并发 + 最小间隔 250ms（保守 4 QPS）+ 429/5xx 重试一次。
- 任何失败（超时/限流/鉴权/余额/解析）都返回空，绝不抛异常。
- Search 结果按 query + 条数做进程内缓存（默认 1h），省额度。
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta
from urllib.parse import urlsplit

from ..config import get_settings
from ..core.http import get_client
from ..core.log import get_logger

log = get_logger("deepseek_search")

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_LOCK = threading.Lock()
_SEM = threading.BoundedSemaphore(3)  # 账号级 5 QPS 下的保守并发
_PACE_LOCK = threading.Lock()
_LAST_CALL = 0.0
_MIN_INTERVAL = 0.25

# R-241：Fetch 正文按 URL 缓存 1h（同一批候选去重后仍可能多次抓同一 URL；重跑同选题直接命中）。
_FETCH_CACHE: dict[str, tuple[float, str]] = {}
_FETCH_CACHE_LOCK = threading.Lock()
_FETCH_CACHE_TTL = 3600.0
_FETCH_CACHE_MAX = 100


def enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.online_search_enabled
        and settings.deepseek_search_enabled
        and settings.deepseek_api_key.strip()
    )


def _api_url(path: str) -> str:
    """拼 API 地址：兼容 `base_url` 是否带 `/v1`（LLM 与搜索共用同一个 base）。"""
    base = (get_settings().deepseek_base_url or "https://api.deepseek.com").rstrip("/")
    if path.startswith("/v1") and base.endswith("/v1"):
        return base + path[len("/v1") :]
    return base + path


def _pace() -> None:
    """全局最小调用间隔：Search 与 Fetch 账号级各 5 QPS，取 4 QPS 保守值。"""
    global _LAST_CALL
    with _PACE_LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.monotonic()


def _post(path: str, body: dict, timeout: float) -> dict | None:
    settings = get_settings()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.deepseek_api_key.strip()}",
    }
    # R-241：共享 httpx.Client（按 DeepSeek base_url 复用连接），每次请求显式 timeout
    try:
        client = get_client(settings.deepseek_base_url)
    except Exception as exc:  # noqa: BLE001 客户端不可用 → 与失败同语义（静默降级）
        log.warning("DeepSeek %s 共享客户端不可用：%s", path, str(exc)[:160])
        return None
    for attempt in (0, 1):
        _pace()
        try:
            with _SEM:
                resp = client.post(
                    _api_url(path), headers=headers, json=body, timeout=max(5.0, timeout)
                )
        except Exception as exc:  # noqa: BLE001 联网失败静默（生成不因此失败）
            log.warning("DeepSeek %s 请求失败：%s", path, str(exc)[:160])
            return None
        if resp.status_code in (408, 429) or resp.status_code >= 500:
            if attempt == 0:
                time.sleep(0.5)
                continue
        if resp.status_code >= 400:
            log.warning("DeepSeek %s HTTP %s：%s", path, resp.status_code, (resp.text or "")[:200])
            return None
        try:
            data = resp.json()
        except ValueError:
            log.warning("DeepSeek %s 返回非 JSON：%s", path, (resp.text or "")[:160])
            return None
        return data if isinstance(data, dict) else None
    return None


def _float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return -1


def _with_time_range(query: str, time_range: str) -> str:
    """把豆包的 TimeRange 口径映射成 DeepSeek 的 `after:` 搜索语法（兼容空值）。"""
    days = {"OneDay": 1, "OneWeek": 7, "OneMonth": 30, "OneYear": 365}.get(time_range)
    if not days:
        return query
    since = date.today() - timedelta(days=days)
    return f"{query} after:{since.isoformat()}"


def _normalize(item: dict) -> dict | None:
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    if not url or not title:
        return None
    return {
        "provider": "deepseek",
        "title": title,
        "url": url,
        "snippet": str(item.get("snippet") or "").strip(),
        "summary": str(item.get("summary") or "").strip(),
        "content": str(item.get("content") or "").strip(),
        "site": str(item.get("site_name") or "").strip() or urlsplit(url).netloc,
        "date": str(item.get("date") or "").strip(),
        "rank": _float(item.get("rerank_score")),
        "authority": _int(item.get("authority")),
    }


def search(query: str, count: int | None = None, time_range: str = "") -> list[dict]:
    """搜索网页：返回归一化结果（含 `content` 正文）；不可用/失败返回 []。"""
    query = (query or "").strip()
    if not query or not enabled():
        return []
    settings = get_settings()
    n = max(1, min(50, int(count or settings.deepseek_search_count or 5)))
    effective_query = _with_time_range(query, time_range)

    cache_key = f"{effective_query}|{n}"
    ttl = max(0, int(settings.web_search_cache_seconds or 0))
    now = time.monotonic()
    if ttl:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and now - hit[0] < ttl:
                return [dict(x) for x in hit[1]]

    data = _post(
        "/v1/tools/search",
        {
            "query": effective_query,
            "count": n,
            "need_content": True,
            "ori_question": query[:128],
        },
        timeout=float(settings.online_search_timeout_seconds or 20),
    )
    if not data:
        return []
    raw = data.get("results")
    if not isinstance(raw, list):
        return []
    results: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            norm = _normalize(item)
            if norm:
                results.append(norm)

    if ttl and results:
        with _CACHE_LOCK:
            if len(_CACHE) > 200:
                _CACHE.clear()
            _CACHE[cache_key] = (now, [dict(x) for x in results])
    return results


def fetch(url: str) -> str:
    """抓取单页 Markdown 正文；失败返回空串（调用方退回摘要）。

    R-241：成功结果按 URL 进程内缓存 1h（上限 100 条），重跑同选题/同批候选不重复抓正文。
    """
    url = (url or "").strip()
    if not url or not enabled():
        return ""
    now = time.monotonic()
    with _FETCH_CACHE_LOCK:
        hit = _FETCH_CACHE.get(url)
        if hit is not None and now - hit[0] < _FETCH_CACHE_TTL:
            return hit[1]
    settings = get_settings()
    data = _post(
        "/v1/tools/fetch",
        {"url": url},
        timeout=float(settings.online_fetch_timeout_seconds or 15),
    )
    if not data:
        return ""
    content = data.get("content")
    text = str(content).strip() if isinstance(content, str) else ""
    if text:
        with _FETCH_CACHE_LOCK:
            if len(_FETCH_CACHE) >= _FETCH_CACHE_MAX:
                _FETCH_CACHE.clear()
            _FETCH_CACHE[url] = (now, text)
    return text
