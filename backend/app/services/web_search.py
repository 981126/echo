"""R-227：豆包搜索（火山引擎融合信息搜索 / 联网搜索）薄客户端。

- 未配置 `ECHO_WEB_SEARCH_API_KEY` → `enabled()` 为 False，调用 `search()` 直接返回 []（静默降级）。
- 同 query 结果进程内缓存（默认 1h），避免重复消耗额度。
- 任何失败（超时/限流/鉴权/解析）都返回 []，绝不抛异常、不阻断生成。
"""

from __future__ import annotations

import threading
import time

from ..config import get_settings
from ..core.http import get_client
from ..core.log import get_logger

log = get_logger("web_search")

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_LOCK = threading.Lock()


def enabled() -> bool:
    settings = get_settings()
    return bool(settings.online_search_enabled and settings.web_search_api_key.strip())


def _pick(item: dict, *keys: str) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _site_of(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return ""


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


def _normalize(item: dict) -> dict:
    url = _pick(item, "Url", "url", "URL")
    return {
        "provider": "doubao",
        "title": _pick(item, "Title", "title"),
        "url": url,
        "snippet": _pick(item, "Snippet", "snippet"),
        "summary": _pick(item, "Summary", "summary", "Snippet", "snippet", "Content"),
        # R-233：豆包 Content 通常与 Summary 等长（600~900 字），仍作为正文候补；
        # `date/rank/authority` 供双源合并排序与界面展示。
        "content": _pick(item, "Content", "content"),
        "site": _pick(item, "SiteName", "site", "Source") or _site_of(url),
        "date": _pick(item, "PublishTime", "date") or "",
        "rank": _float(item.get("RankScore")),
        "authority": _int(item.get("AuthInfoLevel")),
    }


def search(
    query: str,
    count: int | None = None,
    time_range: str = "",
    query_rewrite: bool = True,
) -> list[dict]:
    """联网搜索：返回 [{title,url,summary,site}]；不可用/失败返回 []。

    query_rewrite=True（默认）时开豆包 QueryRewrite，把口语/长句改写成搜索式（R-227）。
    """
    query = (query or "").strip()
    if not query or not enabled():
        return []
    settings = get_settings()
    n = int(count or settings.web_search_count or 5)
    n = max(1, min(50, n))
    cache_key = f"{query}|{n}|{time_range}|{int(query_rewrite)}"
    ttl = max(0, int(settings.web_search_cache_seconds or 0))
    now = time.monotonic()
    if ttl:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and now - hit[0] < ttl:
                return [dict(x) for x in hit[1]]

    body: dict = {"Query": query, "SearchType": "web", "Count": n, "NeedSummary": True}
    if time_range:
        body["TimeRange"] = time_range
    if query_rewrite:
        body["QueryControl"] = {"QueryRewrite": True}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.web_search_api_key.strip()}",
        "X-Traffic-Tag": settings.web_search_traffic_tag or "skill_web_search_common",
    }
    results: list[dict] = []
    timeout = float(settings.web_search_timeout_seconds or 15)
    try:
        # R-241：共享 httpx.Client（keep-alive 复用），每次请求显式 timeout
        client = get_client(settings.web_search_base_url, timeout=timeout)
        resp = client.post(
            settings.web_search_base_url, headers=headers, json=body, timeout=timeout
        )
        if resp.status_code >= 400:
            log.warning("豆包搜索 HTTP %s：%s", resp.status_code, (resp.text or "")[:200])
            return []
        data = resp.json()
        err = ((data or {}).get("ResponseMetadata") or {}).get("Error")
        if err:
            log.warning("豆包搜索返回错误：%s", str(err)[:200])
            return []
        raw = (data.get("Result") or {}).get("WebResults") or []
        for item in raw:
            if isinstance(item, dict):
                norm = _normalize(item)
                if norm["title"] or norm["url"]:
                    results.append(norm)
    except Exception as exc:  # noqa: BLE001 联网失败静默（生成不因此失败）
        log.warning("豆包搜索调用失败：%s", str(exc)[:200])
        return []

    if ttl and results:
        with _CACHE_LOCK:
            if len(_CACHE) > 200:
                _CACHE.clear()
            _CACHE[cache_key] = (now, [dict(x) for x in results])
    return results
