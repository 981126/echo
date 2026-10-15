"""R-227：豆包搜索（火山引擎融合信息搜索 / 联网搜索）薄客户端。

- 未配置 `ECHO_WEB_SEARCH_API_KEY` → `enabled()` 为 False，调用 `search()` 直接返回 []（静默降级）。
- 同 query 结果进程内缓存（默认 1h），避免重复消耗额度。
- 任何失败（超时/限流/鉴权/解析）都返回 []，绝不抛异常、不阻断生成。
"""

from __future__ import annotations

import threading
import time

import httpx

from ..config import get_settings
from ..core.log import get_logger

log = get_logger("web_search")

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_LOCK = threading.Lock()


def enabled() -> bool:
    return bool(get_settings().web_search_api_key.strip())


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


def _normalize(item: dict) -> dict:
    url = _pick(item, "Url", "url", "URL")
    return {
        "title": _pick(item, "Title", "title"),
        "url": url,
        "summary": _pick(item, "Summary", "summary", "Snippet", "snippet", "Content"),
        "site": _pick(item, "SiteName", "site", "Source") or _site_of(url),
    }


def search(query: str, count: int | None = None, time_range: str = "") -> list[dict]:
    """联网搜索：返回 [{title,url,summary,site}]；不可用/失败返回 []。"""
    query = (query or "").strip()
    if not query or not enabled():
        return []
    settings = get_settings()
    n = int(count or settings.web_search_count or 5)
    n = max(1, min(50, n))
    cache_key = f"{query}|{n}|{time_range}"
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
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.web_search_api_key.strip()}",
        "X-Traffic-Tag": settings.web_search_traffic_tag or "skill_web_search_common",
    }
    results: list[dict] = []
    try:
        with httpx.Client(timeout=float(settings.web_search_timeout_seconds or 15)) as client:
            resp = client.post(settings.web_search_base_url, headers=headers, json=body)
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
