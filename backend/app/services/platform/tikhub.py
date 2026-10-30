"""TikHub 平台数据适配器（M13，R-027/R-029）。

模式：
- mock：离线确定性数据，用于开发/测试/验收（当前默认，作者确认先 mock）。
- real：走 TikHub REST API（Authorization: Bearer ECHO_TIKHUB_API_KEY）。
  抖音 App V3 / 小红书 App V2 / B站 Web；每个平台独立 try/except，单平台失败不影响整体。
视频一律不下载（省额度）；封面在 sync 服务里下载/占位。

外部文档：https://docs.tikhub.io
"""

from __future__ import annotations

import hashlib
import math
import random
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from ...config import get_settings
from ...core.log import get_logger
from ...core.timeutil import now as _app_now
from ..text_tags import extract_hashtags
from .base import CommentData, PostData, ProfileData  # noqa: E402,F401
from .link_utils import parse_link, parse_post_id  # noqa: F401  re-export：保持旧导入路径

log = get_logger("tikhub")

PLATFORMS = ["douyin", "xiaohongshu", "bilibili"]
PLATFORM_LABEL = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}

# R-163：TikHub 上限改为「全局合计 10 请求/秒」（TikHub 套餐口径），因此不再默认「按路由 1.2s 串行」
# ——那会让同一平台所有账号/帖子互相排队，是同步慢的主因。现在：
#   ① 全局令牌桶（所有接口共享，速率/容量可配）保证合计 ≤ 上限；
#   ② 保留按路由的**基础间隔**（`_ROUTE_MIN_INTERVAL`，默认 0 关闭）与 **429 退避**兜底：
#      某路由被服务端限流时临时抬高该路由的下次允许时间，避免持续撞 429。
# 同时保留 R-151 的瞬时故障（TransportError/429/5xx）有界重试，避免一次抖动判失败。
_ROUTE_MIN_INTERVAL = 0.0  # 秒；默认不做按路由强制排队（R-163），由全局令牌桶控速
_ROUTE_BACKOFF_SECONDS = 2.0  # 某路由 429 后，临时抬高该路由下次允许时间的秒数（兜底）
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4  # 首次 + 3 次重试（实测：只重试 2 次时，补跑 60 条仍有 3 条撞上代理抖动窗口而失败）
_RETRY_DELAYS = (1.5, 4.0, 8.0)
_ROUTE_LAST: dict[str, float] = {}
_ROUTE_BACKOFF: dict[str, float] = {}
_ROUTE_LOCK = threading.Lock()


class _TokenBucket:
    """线程安全令牌桶：按 `rate` req/s 补充令牌，容量 `capacity`（限制瞬时突发）。

    `acquire()` 先锁内**预留**令牌（可为负），再锁外 sleep，避免并发线程同时挤在同一时刻发车。
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate = max(0.01, float(rate))
        self.capacity = max(1, int(capacity))
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, n: int = 1) -> None:
        """R-222：支持批量获取 n 个令牌，让并行请求能一次性拿足配额。"""
        n = max(1, int(n))
        with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self.updated)
            self.updated = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.tokens -= float(n)
            wait = -self.tokens / self.rate if self.tokens < 0 else 0.0
        if wait > 0:
            time.sleep(wait)


_GLOBAL_BUCKET: _TokenBucket | None = None
_GLOBAL_LOCK = threading.Lock()


def _global_bucket() -> _TokenBucket:
    """按当前配置惰性构建全局令牌桶（.env 改动需重启生效，与其它配置一致）。"""
    global _GLOBAL_BUCKET
    if _GLOBAL_BUCKET is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_BUCKET is None:
                settings = get_settings()
                _GLOBAL_BUCKET = _TokenBucket(settings.tikhub_rate_limit, settings.tikhub_rate_burst)
    return _GLOBAL_BUCKET


def _penalize_route(path: str, seconds: float = _ROUTE_BACKOFF_SECONDS) -> None:
    """某路由被限流（429）时临时抬高其下次允许时间（按路由退避兜底）。"""
    with _ROUTE_LOCK:
        _ROUTE_BACKOFF[path] = max(_ROUTE_BACKOFF.get(path, 0.0), time.monotonic() + seconds)


def _throttle_route(path: str) -> None:
    """发请求前控速：先过全局令牌桶，再按路由基础间隔 / 429 退避排队（线程安全）。"""
    _global_bucket().acquire()
    with _ROUTE_LOCK:
        now = time.monotonic()
        at = max(now, _ROUTE_LAST.get(path, 0.0) + _ROUTE_MIN_INTERVAL)
        backoff = _ROUTE_BACKOFF.get(path, 0.0)
        if backoff > at:
            at = backoff
        _ROUTE_LAST[path] = at
    delay = at - now
    if delay > 0:
        time.sleep(delay)


def _reset_limiter() -> None:
    """测试用：清空全局令牌桶与路由状态（生产不调用）。"""
    global _GLOBAL_BUCKET
    with _GLOBAL_LOCK:
        _GLOBAL_BUCKET = None
    with _ROUTE_LOCK:
        _ROUTE_LAST.clear()
        _ROUTE_BACKOFF.clear()

# 主页链接解析规则：platform -> (正则组名/顺序)
def _is_benchmark_account(account) -> bool:
    """对标账号识别（R-109 统一每日同步后不再靠 weekly 频率）：
    优先按归属博主 kind；兼容历史 weekly 频率标记；异常时保守返回 False（仅影响 mock 假数据规模）。
    """
    if account is None:
        return False
    if getattr(account, "sync_frequency", "") == "weekly":
        return True
    try:
        creator = getattr(account, "creator", None)
    except Exception:  # noqa: BLE001  懒加载/会话关闭等异常保守处理
        creator = None
    return bool(creator and getattr(creator, "kind", "") == "benchmark")


_LINK_RULES = {
    "douyin": [("douyin.com/user/", "MS4w"), ("v.douyin.com", "")],
    "xiaohongshu": [("xiaohongshu.com/user/profile", "userId"), ("xhslink.com", "")],
    "bilibili": [("space.bilibili.com/", "uid")],
}

_TITLE_POOL = {
    "douyin": [
        "大厂秋招缩编，应届生该先就业还是再等等",
        "月薪 8 千和 1 万五的 offer 怎么选",
        "裸辞一年后我后悔了吗",
        "35 岁转行还来得及吗",
        "面试被问离职原因，怎么答不扣分",
        "简历上哪些词一写就废",
        "HR 筛简历 10 秒看什么",
        "谈薪时说这句话，直接少拿两千",
        "为什么你的内容没人看：选题在作祟",
        "口播别端着，像跟朋友说话才有流量",
        "副业第一周别急着赚钱，先做这三件事",
        "面试官最反感的三个小动作",
    ],
    "xiaohongshu": [
        "应届生第一份工作：大厂还是小厂",
        "谈薪时最不该说的一句话",
        "面试被问职业规划怎么答不扣分",
        "下班副业从哪开始：先做这 3 件事",
        "简历别造假，但要学会'会写'",
        "文科生能转的 6 个高薪方向",
        "打工人时间管理：下班后 2 小时怎么用",
        "搞副业先别辞职，除非你算清这笔账",
        "普通人做自媒体的第一个月怎么熬",
        "被裁后我靠这招一个月拿到 4 个 offer",
        "内向的人怎么在面试里显得有气场",
        "通勤路上听什么，一年拉开差距",
    ],
    "bilibili": [
        "程序员 35 岁危机是伪命题吗",
        "副业月入过万的真实成本",
        "知识博主日更 30 天的变化",
        "转行程序员一年后我后悔了吗",
        "为什么你面试总挂在同一轮",
        "普通人 3 个月学会一项能赚钱的技能",
        "上班摸鱼搞副业，被发现了怎么办",
        "用 AI 写脚本前，先搞懂这 3 件事",
        "从月薪 5 千到 2 万，我做对了什么",
        "应届生必看：试用期被裁合法吗",
        "聊聊面试里最容易翻车的 5 个问题",
        "我为什么劝你先别裸辞",
    ],
}

_COMMENT_POOL = [
    "这个选题好真实，蹲一个后续",
    "请问应届生第一份工作怎么选才不后悔？",
    "面试被问缺点，怎么答才能不扣分？",
    "裸辞到底需要存多少钱才安全？",
    "怎么判断一个副业是不是割韭菜？",
    "简历空窗期要怎么写才好看？",
    "谈薪被压价，还有机会再争取吗？",
    "30 岁转行会不会太晚了？",
    "口播总是像背课文，怎么改？",
    "想知道普通人做自媒体第一周该发什么",
    "下班后 2 小时怎么安排最高效？",
    "大厂和小厂 offer 你会怎么选？",
    "AI 时代哪些岗位最容易被替代？",
    "怎么让老板看到我的工作量？",
    "考证到底有没有用？求真实经验",
    "面试官问'你还有什么问题吗'怎么回？",
]


def _tags_of(*texts: str) -> list[str]:
    """解析 #话题 标签（去重、去纯平台词）。R-226：统一走 text_tags.extract_hashtags。"""
    return extract_hashtags(*texts)


def _seed_id(user_id: str, salt: str = "") -> int:
    return int(hashlib.md5(f"{user_id}:{salt}".encode()).hexdigest(), 16)


class TikHubError(RuntimeError):
    pass


class TikHubBusinessError(TikHubError):
    """HTTP 200 但响应体内是业务错误码（如 creator_v2 透传抖音的 status_code=8 用户未登录）。

    R-237 真实联调发现：creator_v2 系列 HTTP 200 只代表 TikHub 代理调用成功，
    业务错误在 body 的 `status_code/status_msg` 或 `BaseResp.StatusCode` 里。
    """

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


# 抖音创作者平台错误码 → 可读中文；8 = 用户未登录（Cookie 失效/未登录）
_CREATOR_ERROR_HINTS = {
    8: "Cookie 未登录或已过期，请在「视频复盘 → 抖音数据设置」重新保存创作者中心 Cookie",
    5: "Cookie 已过期，请重新保存创作者中心 Cookie",
    20: "当前账号没有该作品的查看权限",
}


def _business_error(body: dict) -> tuple[int | None, str]:
    """识别 HTTP 200 响应体里的业务错误码；返回 (code, message)，无错误返回 (None, "")。"""
    if not isinstance(body, dict):
        return None, ""
    for node in (body, body.get("data")):
        if not isinstance(node, dict):
            continue
        code = node.get("status_code")
        if isinstance(code, (int, float)) and int(code) not in (0, 200):
            message = str(node.get("status_msg") or node.get("message") or "").strip()
            return int(code), message
        base = node.get("BaseResp")
        if isinstance(base, dict):
            code = base.get("StatusCode")
            if isinstance(code, (int, float)) and int(code) not in (0,):
                return int(code), str(base.get("StatusMessage") or "").strip()
    code = body.get("code")
    if isinstance(code, (int, float)) and int(code) not in (0, 200):
        return int(code), str(body.get("message_zh") or body.get("message") or "").strip()
    return None, ""


def _raise_business_error(path: str, body: dict) -> None:
    code, message = _business_error(body)
    if code is None:
        return
    hint = _CREATOR_ERROR_HINTS.get(code)
    detail = hint or message or "平台返回业务错误"
    if message and message not in detail:
        detail = f"{detail}（平台提示：{message}）"
    raise TikHubBusinessError(f"TikHub 业务错误 {code}（{path}）：{detail}", code=code)



def _first_url(items) -> str:
    for u in items or []:
        if u and isinstance(u, str):
            return u
    return ""


def _note_payload(data: dict) -> dict | None:
    """从小红书 get_video_note_detail 响应里取出笔记 dict（兼容不同层级/包装）。"""
    node = (data.get("data") or {}).get("data")
    if isinstance(node, list):
        return node[0] if node and isinstance(node[0], dict) else None
    if isinstance(node, dict):
        if "note" in node and isinstance(node["note"], dict):
            return node["note"]
        # 本身即是笔记（含 video_info_v2/id 等）
        if "video_info_v2" in node or "id" in node:
            return node
    return None


def _first_media_url(item: dict) -> str:
    """dash 流地址：baseUrl 可能是字符串或数组，backupUrl 兜底。"""
    base = item.get("baseUrl") or ""
    if isinstance(base, str) and base:
        return base
    if isinstance(base, list):
        u = _first_url(base)
        if u:
            return u
    return _first_url(item.get("backupUrl") or [])


def _find_urls_like(obj, needles) -> list[str]:
    """深度遍历 dict/list，收集值里疑似媒体直链的字符串（含任一 needle）。"""
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif (
            isinstance(node, str)
            and node.startswith("http")
            and len(node) > 12
            and any(n in node for n in needles)
        ):
            out.append(node)

    walk(obj)
    return out


class TikHubClient:
    """三平台统一客户端。mock 返回确定性数据；real 走 REST（无 key 时抛错）。"""

    def __init__(self, mode: str = "", api_key: str = "", base_url: str = ""):
        settings = get_settings()
        self.mode = (mode or settings.tikhub_mode or "mock").strip().lower()
        self.api_key = api_key or settings.tikhub_api_key
        self.base_url = (base_url or settings.tikhub_base_url).rstrip("/")
        self._requests = 0
        # R-241：make_client 返回进程级单例后，requests_used 会被多线程并发累加。
        # 计费方都是「同一线程内 before=requests_used…结束后取差值」，因此对外暴露
        # **线程内累计值**（threading.local）：各并发消费者差值精确、不会把别人的请求算进
        # 自己的预算；`total_requests_used` 保留全局累计供观测。
        self._requests_lock = threading.Lock()
        self._local = threading.local()

    def _http(self) -> httpx.Client:
        """R-241：使用进程级共享 httpx.Client（按 base_url 复用连接；线程安全）。"""
        from ...core.http import get_client

        return get_client(
            self.base_url,
            follow_redirects=True,
            timeout=httpx.Timeout(connect=20, read=12, write=60, pool=20),
        )

    def _bump_request(self) -> None:
        with self._requests_lock:
            self._requests += 1
        self._local.count = int(getattr(self._local, "count", 0)) + 1

    @property
    def requests_used(self) -> int:
        """当前线程在该 client 上的累计请求数（差值计费口径；进程级单例下按线程隔离）。"""
        return int(getattr(self._local, "count", 0))

    @property
    def total_requests_used(self) -> int:
        """进程内该 client 的全局累计请求数（观测用，不作计费口径）。"""
        return self._requests

    # ---------- 内部 ----------
    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET 一个 TikHub 接口，带同路由限速与瞬时故障重试（R-151）。

        重试条件：`httpx.TransportError`（SSL EOF/连接重置/超时等瞬时故障）或 HTTP 429/5xx；
        其余 4xx 属永久错误（参数/权限/额度），立即抛出不浪费额度。
        """
        if not self.api_key:
            raise TikHubError("未配置 ECHO_TIKHUB_API_KEY（real 模式需要）")
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last = "未知错误"
        last_exc: httpx.TransportError | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            _throttle_route(path)
            self._bump_request()
            try:
                resp = self._http().get(url, params=params, headers=headers)
            except httpx.TransportError as exc:  # 代理掐断/连接重置/读写超时等瞬时故障
                last = f"{type(exc).__name__}: {exc}"
                last_exc = exc
            else:
                if resp.status_code < 400:
                    body = resp.json()
                    _raise_business_error(path, body)
                    return body
                last = f"HTTP {resp.status_code} {resp.text[:200]}"
                if resp.status_code == 429:
                    _penalize_route(path)  # R-163：按路由退避兜底，避免持续撞限流
                if resp.status_code not in _RETRYABLE_STATUS:
                    log.warning("TikHub 请求失败（不重试）：%s %s", path, last[:300])
                    raise TikHubError(f"TikHub 请求失败: {last}")
            if attempt < _MAX_ATTEMPTS:
                delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                log.warning("TikHub 请求失败，%.1fs 后重试（第 %d/%d 次）：%s %s", delay, attempt, _MAX_ATTEMPTS - 1, path, last[:200])
                time.sleep(delay)
        log.error("TikHub 请求失败（已尝试 %d 次）：%s %s", _MAX_ATTEMPTS, path, last[:300])
        message = f"TikHub 请求失败（已重试 {_MAX_ATTEMPTS - 1} 次）: {last}"
        if last_exc is not None:
            raise TikHubError(message) from last_exc
        raise TikHubError(message)

    def _post(self, path: str, payload: dict, params: dict | None = None) -> dict:
        """POST JSON，复用全局限速与重试；请求体可能含 Cookie，绝不记录。"""
        if not self.api_key:
            raise TikHubError("未配置 ECHO_TIKHUB_API_KEY（real 模式需要）")
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last = "未知错误"
        last_exc: httpx.TransportError | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            _throttle_route(path)
            self._bump_request()
            try:
                resp = self._http().post(url, params=params, json=payload, headers=headers)
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
                last_exc = exc
            else:
                if resp.status_code < 400:
                    body = resp.json()
                    _raise_business_error(path, body)
                    return body
                last = f"HTTP {resp.status_code} {resp.text[:200]}"
                if resp.status_code == 429:
                    _penalize_route(path)
                if resp.status_code not in _RETRYABLE_STATUS:
                    raise TikHubError(f"TikHub 请求失败: {last}")
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
        message = f"TikHub 请求失败（已重试 {_MAX_ATTEMPTS - 1} 次）: {last}"
        if last_exc is not None:
            raise TikHubError(message) from last_exc
        raise TikHubError(message)

    def fetch_douyin_creator_item_list(
        self, *, cookie: str, start_time: int, end_time: int, count: int = 100, cursor: int | None = None
    ) -> dict:
        if self.mode != "real":
            return {"items": [], "has_more": False}
        payload: dict = {
            "cookie": cookie,
            "start_time": start_time,
            "end_time": end_time,
            "count": min(100, max(1, count)),
            "fields": "metrics,review,visibility",
        }
        if cursor is not None:
            payload["cursor"] = cursor
        return self._post("/douyin/creator_v2/fetch_item_list", payload)

    def fetch_douyin_creator_overview(self, *, cookie: str, item_id: str) -> dict:
        if self.mode != "real":
            seed = int(hashlib.sha256(item_id.encode()).hexdigest()[:6], 16)
            # R-237：mock 对齐真实 creator_v2 字段名（短视频创作者中心），避免测试掩盖真实映射问题
            return {
                "data": {
                    "items": [{
                        "id": item_id,
                        "create_time": str(int(_app_now().timestamp())),
                        "video_info": {"duration": "85774"},
                        "metrics": {
                            "view_count": str(6734 + seed % 40000),
                            "like_count": str(500 + seed % 2500),
                            "comment_count": str(20 + seed % 300),
                            "share_count": str(10 + seed % 150),
                            "favorite_count": str(30 + seed % 500),
                            "bounce_rate_2s": f"{0.2 + (seed % 20) / 100:.6f}",
                            "completion_rate_5s": f"{0.45 + (seed % 30) / 100:.6f}",
                            "completion_rate": f"{0.15 + (seed % 35) / 100:.6f}",
                            "avg_view_second": f"{20 + seed % 70:.6f}",
                            "homepage_visit_count": str(50 + seed % 1000),
                            "subscribe_count": str(seed % 300),
                            "unsubscribe_count": str(seed % 50),
                        },
                    }],
                    "status_code": 0,
                    "status_msg": "",
                }
            }
        return self._post(
            "/douyin/creator_v2/fetch_item_overview_data",
            {"cookie": cookie, "ids": item_id, "fields": "metrics,play_info,content_analysis"},
        )

    def fetch_douyin_creator_play_source(self, *, cookie: str, item_id: str) -> dict:
        if self.mode != "real":
            return {
                "data": {
                    "play_source": [
                        {"key": "homepage_hot", "value": 0.72},
                        {"key": "search", "value": 0.18},
                        {"key": "homepage", "value": 0.1},
                    ],
                    "status_code": 0,
                }
            }
        return self._post("/douyin/creator_v2/fetch_item_play_source", {"cookie": cookie, "item_id": item_id})

    def fetch_douyin_creator_search_keyword(self, *, cookie: str, item_id: str) -> dict:
        if self.mode != "real":
            return {
                "data": {
                    "id": item_id,
                    "inspire_search": [{"keyword": "面试技巧", "percent": 0.32}],
                    "show_from": [{"keyword": "自我介绍", "percent": 0.18}],
                    "status_code": 0,
                }
            }
        return self._post("/douyin/creator_v2/fetch_item_search_keyword", {"cookie": cookie, "item_id": item_id})

    def fetch_douyin_watch_trend(self, *, cookie: str, item_id: str, analysis_type: int) -> dict:
        if analysis_type not in (1, 2, 7):
            raise ValueError("analysis_type 只支持 1/2/7")
        if self.mode != "real":
            values = [0.82, 0.68, 0.55, 0.41, 0.32, 0.25]
            if analysis_type == 2:
                values = [0.01, 0.03, 0.08, 0.12, 0.07, 0.04]
            elif analysis_type == 7:
                values = [0.05, 0.12, 0.08, 0.18, 0.09, 0.07]
            return {
                "analysis_trend": {
                    "current_item": [{"key": f"00:{i * 10:02d}", "value": v} for i, v in enumerate(values)],
                    "similar_author": [{"key": f"00:{i * 10:02d}", "value": max(0.01, v - 0.05)} for i, v in enumerate(values)],
                }
            }
        return self._post(
            "/douyin/creator_v2/fetch_item_watch_trend",
            {"cookie": cookie, "item_id": item_id, "analysis_type": analysis_type},
        )

    def fetch_douyin_low_fan(
        self, *, page: int = 1, page_size: int = 20, date_window: int = 168, keyword: str = "", tags: list | None = None
    ) -> dict:
        if self.mode != "real":
            return {"items": []}
        return self._post(
            "/douyin/billboard/fetch_hot_total_low_fan_list",
            {"page": page, "page_size": page_size, "date_window": date_window, "keyword": keyword, "tags": tags or []},
        )

    def search_douyin_items(
        self, *, query: str, category_id: str = "0", date_type: int = 7, label_type: int = 1, duration_type: int = 0
    ) -> dict:
        if self.mode != "real":
            return {"items": []}
        return self._post(
            "/douyin/index/fetch_item_query",
            {},
            params={
                "query": query,
                "category_id": category_id,
                "date_type": date_type,
                "label_type": label_type,
                "duration_type": duration_type,
            },
        )

    def fetch_douyin_video_statistics(self, item_ids: str | list[str]) -> dict:
        """作品统计（播放/点赞/评论/分享）。aweme_ids 支持逗号分隔，官方上限 2 个/请求。"""
        ids = item_ids if isinstance(item_ids, str) else ",".join(str(x) for x in item_ids)
        if self.mode != "real":
            seed = int(hashlib.sha256(ids.encode()).hexdigest()[:6], 16)
            return {
                "data": {
                    "statistics_list": [
                        {
                            "aweme_id": ids.split(",")[0],
                            "play_count": 50000 + seed % 200000,
                            "digg_count": 1000 + seed % 5000,
                            "share_count": seed % 300,
                            "comment_count": seed % 500,
                        }
                    ]
                }
            }
        return self._get("/douyin/app/v3/fetch_video_statistics", {"aweme_ids": ids})

    # ---------- 余额 ----------
    def get_balance(self) -> dict:
        if self.mode != "real":
            return {"mode": "mock", "balance": 999999, "unit": "mock"}
        data = self._get("/tikhub/user/get_user_info")
        return {"mode": "real", "balance": data, "unit": "raw"}

    # ---------- 主页信息 ----------
    def fetch_profile(self, platform: str, user_id: str, account=None) -> ProfileData:
        if self.mode == "real":
            return self._real_profile(platform, user_id)
        return self._mock_profile(platform, user_id, account)

    def _mock_profile(self, platform: str, user_id: str, account=None) -> ProfileData:
        rnd = random.Random(_seed_id(user_id, platform))
        scale = rnd.choice([1, 3, 8, 15, 40]) * 1000
        is_bench = _is_benchmark_account(account)
        if is_bench:
            scale = int(scale * 2.2)
        nickname = getattr(account, "nickname", "") or f"{PLATFORM_LABEL.get(platform, platform)}博主"
        return ProfileData(
            nickname=nickname,
            followers=rnd.randint(20, 200) * scale,
            likes_total=rnd.randint(50, 500) * scale * 3,
            posts_total=rnd.randint(60, 260),
            following=rnd.randint(10, 300),
            raw={"mode": "mock"},
        )

    def _real_profile(self, platform: str, user_id: str) -> ProfileData:
        if platform == "douyin":
            data = self._get("/douyin/app/v3/handler_user_profile", {"sec_user_id": user_id})
            user = ((data.get("data") or {}).get("user") or {})
            avatar = ((user.get("avatar_thumb") or {}).get("url_list") or [""])[0]
            return ProfileData(
                nickname=user.get("nickname", ""),
                avatar_url=avatar or "",
                followers=int(user.get("follower_count") or 0),
                likes_total=int(user.get("total_favorited") or 0),
                posts_total=int(user.get("aweme_count") or 0),
                following=int(user.get("following_count") or 0),
                raw=data,
            )
        if platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_user_info", {"user_id": user_id})
            d = ((data.get("data") or {}).get("data")) or {}
            posted = ((d.get("note_num_stat") or {}).get("posted")) or 0
            return ProfileData(
                nickname=d.get("nickname", ""),
                avatar_url="",  # 小红书该接口不返回头像，保持空圆框
                followers=int(d.get("fans") or 0),
                likes_total=int(d.get("liked") or 0),
                posts_total=int(posted or 0),
                following=0,
                raw=data,
            )
        # bilibili：app 用户卡片（name/fans/face）
        data = self._get("/bilibili/app/fetch_user_info", {"user_id": user_id})
        inner = ((data.get("data") or {}).get("data")) or {}
        card = inner.get("card") or {}
        archive_count = ((inner.get("archive") or {}).get("count")) or 0
        def _num(v):
            if isinstance(v, dict):
                v = v.get("count") or v.get("total") or 0
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0

        return ProfileData(
            nickname=card.get("name", ""),
            avatar_url=card.get("face") or "",
            followers=_num(card.get("fans")),
            likes_total=_num(card.get("likes")),
            posts_total=_num(card.get("videos")) or _num(archive_count),
            following=_num(card.get("attention")),
            raw=data,
        )

    # ---------- 作品列表 ----------
    def fetch_user_posts(self, platform: str, user_id: str, count: int = 20, cursor: str = "", account=None) -> list[PostData]:
        if self.mode == "real":
            if count <= 0:
                return self._real_posts_all(platform, user_id)
            return self._real_posts(platform, user_id, count)
        return self._mock_posts(platform, user_id, count, account)

    def _real_posts_all(self, platform: str, user_id: str, max_pages: int = 200) -> list[PostData]:
        """全量拉取该用户全部作品：翻页直到平台返回 has_more=false（无作品数量硬上限）。"""
        out: list[PostData] = []
        if platform == "douyin":
            cursor = ""
            pages = 0
            while pages < max_pages:
                pages += 1
                params: dict = {"sec_user_id": user_id, "count": 30}
                if cursor:
                    params["max_cursor"] = cursor
                try:
                    data = self._get("/douyin/app/v3/fetch_user_post_videos", params)
                except TikHubError:
                    break  # 单页失败跳过，不让整批失败
                d = data.get("data") or {}
                aweme_list = d.get("aweme_list") or []
                for aw in aweme_list:
                    stat = aw.get("statistics") or {}
                    out.append(
                        PostData(
                            platform_post_id=str(aw.get("aweme_id") or ""),
                            title=((aw.get("desc") or "")[:200]),
                            desc=aw.get("desc") or "",
                            tags=_tags_of(aw.get("desc") or ""),
                            cover_url=((((aw.get("video") or {}).get("cover") or {}).get("url_list") or [""])[0]),
                            video_url=((((aw.get("video") or {}).get("play_addr") or {}).get("url_list") or [""])[0]),
                            publish_time=_ts(aw.get("create_time")),
                            stats={
                                "plays": int(stat.get("play_count") or 0),
                                "likes": int(stat.get("digg_count") or 0),
                                "favorites": int(stat.get("collect_count") or 0),
                                "shares": int(stat.get("share_count") or 0),
                                "comments": int(stat.get("comment_count") or 0),
                                "extra": {},
                            },
                            raw=aw,
                        )
                    )
                next_cursor = str(d.get("max_cursor") or "")
                if not aweme_list or not d.get("has_more") or next_cursor == cursor:
                    break
                cursor = next_cursor
        elif platform == "xiaohongshu":
            cursor = ""
            pages = 0
            while pages < max_pages:
                pages += 1
                try:
                    data = self._get("/xiaohongshu/app_v2/get_user_posted_notes", {"user_id": user_id, "cursor": cursor or ""})
                except TikHubError:
                    break
                inner = (((data.get("data") or {}).get("data")) or {})
                notes = inner.get("notes") or []
                for n in notes:
                    cover = ""
                    imgs = n.get("images_list") or []
                    if imgs and isinstance(imgs[0], dict):
                        img0 = imgs[0]
                        cover = (img0.get("url_list") or [""])[0] or img0.get("url") or img0.get("url_size_large") or ""
                    out.append(
                        PostData(
                            platform_post_id=str(n.get("id") or n.get("note_id") or ""),
                            title=(n.get("title") or n.get("display_title") or "")[:200],
                            desc=n.get("desc") or "",
                            tags=_tags_of(n.get("title") or "", n.get("desc") or ""),
                            cover_url=cover or "",
                            video_url="",
                            publish_time=_ts(n.get("create_time") or n.get("time")),
                            stats={
                                "plays": int(n.get("view_count") or 0),
                                "likes": int(n.get("likes") or 0),
                                "favorites": int(n.get("collected_count") or 0),
                                "shares": int(n.get("share_count") or 0),
                                "comments": int(n.get("comments_count") or 0),
                                "extra": {},
                            },
                            raw=n,
                        )
                    )
                if not notes or not inner.get("has_more"):
                    break
                last_cursor = str((notes[-1].get("cursor") or ""))
                if not last_cursor or last_cursor == cursor:
                    break
                cursor = last_cursor
        else:  # bilibili
            page = 1
            seen_aids: set[str] = set()
            total_pages = None
            while page <= 120:
                try:
                    data = self._get("/bilibili/web/fetch_user_post_videos_v2", {"uid": user_id, "pn": page, "ps": 30})
                except TikHubError:
                    break
                inner_data = (((data.get("data") or {}).get("data")) or {})
                vlist = inner_data.get("archives") or []
                page_info = inner_data.get("page") or {}
                if total_pages is None:
                    total = int(page_info.get("total") or 0)
                    if total > 0:
                        total_pages = math.ceil(total / 30)
                for v in vlist:
                    aid = str(v.get("aid") or "")
                    if aid in seen_aids:
                        continue
                    seen_aids.add(aid)
                    stat = v.get("stat") or {}
                    # 全量：只存列表自带的 view（避免上百次详情请求拖慢）；赞藏评由“同步前10条”补全
                    stats = {
                        "plays": int(stat.get("view") or 0),
                        "likes": int(stat.get("like") or 0),
                        "favorites": int(stat.get("favorite") or 0),
                        "shares": int(stat.get("share") or 0),
                        "comments": int(stat.get("reply") or 0),
                        "extra": {"danmaku": int(stat.get("danmaku") or 0), "coin": int(stat.get("coin") or 0)},
                    }
                    out.append(
                        PostData(
                            platform_post_id=f"aid:{v.get('aid') or ''}",
                            title=v.get("title") or "",
                            desc=v.get("desc") or "",
                            tags=_tags_of(v.get("title") or "", v.get("desc") or ""),
                            cover_url=v.get("pic") or "",
                            video_url="",
                            publish_time=_ts(v.get("pubdate") or v.get("created")),
                            stats=stats,
                            raw=v,
                        )
                    )
                # 分页重叠容错：即使某页全是重复（新投稿插队导致），也要翻到预期页数之后再多翻几页
                if not vlist:
                    break
                if total_pages is not None and page >= total_pages + 3:
                    break
                if len(vlist) < 30 and page >= (total_pages or 1):
                    break
                page += 1
        return out

    def _mock_posts(self, platform: str, user_id: str, count: int, account=None) -> list[PostData]:
        rnd = random.Random(_seed_id(user_id, platform))
        pool = _TITLE_POOL.get(platform, _TITLE_POOL["douyin"])
        out: list[PostData] = []
        now = _app_now()
        limit = 60 if count <= 0 else min(count, 60)  # count<=0 = 全量（mock 取满样本）
        for i in range(limit):
            idx = (rnd.randint(0, 10**6) + i) % len(pool)
            post_id = f"{platform}_{str(_seed_id(user_id, str(i)))[-10:]}{i}"
            plays = rnd.randint(3000, 800000)
            likes = int(plays * rnd.uniform(0.02, 0.09))
            favorites = int(likes * rnd.uniform(0.3, 0.8))
            shares = int(likes * rnd.uniform(0.05, 0.2))
            comments = int(likes * rnd.uniform(0.02, 0.08))
            out.append(
                PostData(
                    platform_post_id=post_id,
                    title=pool[idx],
                    desc=f"#{PLATFORM_LABEL.get(platform, platform)} 干货 · {pool[idx]}",
                    cover_url="",
                    video_url="",  # 不下载视频
                    publish_time=now - timedelta(days=i * 2 + rnd.randint(0, 1)),
                    stats={
                        "plays": plays,
                        "likes": likes,
                        "favorites": favorites,
                        "shares": shares,
                        "comments": comments,
                        "extra": {"platform_extra": rnd.randint(0, 50)} if platform == "bilibili" else {},
                    },
                    raw={"mode": "mock", "index": i},
                )
            )
        return out

    def _real_posts(self, platform: str, user_id: str, count: int) -> list[PostData]:
        out: list[PostData] = []
        if platform == "douyin":
            data = self._get("/douyin/app/v3/fetch_user_post_videos", {"sec_user_id": user_id, "count": min(count, 30)})
            aweme_list = (data.get("data") or {}).get("aweme_list") or []
            for aw in aweme_list:
                stat = aw.get("statistics") or {}
                out.append(
                    PostData(
                        platform_post_id=str(aw.get("aweme_id") or ""),
                        title=((aw.get("desc") or "")[:200]),
                        desc=aw.get("desc") or "",
                        cover_url=((((aw.get("video") or {}).get("cover") or {}).get("url_list") or [""])[0]),
                        video_url=((((aw.get("video") or {}).get("play_addr") or {}).get("url_list") or [""])[0]),
                        publish_time=_ts(aw.get("create_time")),
                        stats={
                            "plays": int(stat.get("play_count") or 0),
                            "likes": int(stat.get("digg_count") or 0),
                            "favorites": int(stat.get("collect_count") or 0),
                            "shares": int(stat.get("share_count") or 0),
                            "comments": int(stat.get("comment_count") or 0),
                            "extra": {},
                        },
                        raw=aw,
                    )
                )
        elif platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_user_posted_notes", {"user_id": user_id, "cursor": ""})
            notes = (((data.get("data") or {}).get("data")) or {}).get("notes") or []
            for n in notes[:count]:
                cover = ""
                imgs = n.get("images_list") or []
                if imgs and isinstance(imgs[0], dict):
                    img0 = imgs[0]
                    cover = (
                        (img0.get("url_list") or [""])[0]
                        or img0.get("url")
                        or img0.get("url_size_large")
                        or ""
                    )
                out.append(
                    PostData(
                        platform_post_id=str(n.get("id") or n.get("note_id") or ""),
                        title=(n.get("title") or n.get("display_title") or "")[:200],
                        desc=n.get("desc") or "",
                        cover_url=cover or "",
                        video_url="",
                        publish_time=_ts(n.get("create_time") or n.get("time")),
                        stats={
                            "plays": int(n.get("view_count") or 0),
                            "likes": int(n.get("likes") or 0),
                            "favorites": int(n.get("collected_count") or 0),
                            "shares": int(n.get("share_count") or 0),
                            "comments": int(n.get("comments_count") or 0),
                            "extra": {},
                        },
                        raw=n,
                    )
                )
        else:  # bilibili（web 列表只含 view，其余走单条详情）
            data = self._get("/bilibili/web/fetch_user_post_videos_v2", {"uid": user_id, "page_num": 1, "page_size": min(count, 30)})
            vlist = ((((data.get("data") or {}).get("data")) or {}).get("archives")) or []
            for v in vlist[:count]:
                stat = v.get("stat") or {}
                stats = {}
                if "like" in stat:
                    stats = {
                        "plays": int(stat.get("view") or 0),
                        "likes": int(stat.get("like") or 0),
                        "favorites": int(stat.get("favorite") or 0),
                        "shares": int(stat.get("share") or 0),
                        "comments": int(stat.get("reply") or 0),
                        "extra": {"danmaku": int(stat.get("danmaku") or 0), "coin": int(stat.get("coin") or 0)},
                    }
                out.append(
                    PostData(
                        platform_post_id=f"aid:{v.get('aid') or ''}",
                        title=v.get("title") or "",
                        desc=v.get("desc") or "",
                        cover_url=v.get("pic") or "",
                        video_url="",
                        publish_time=_ts(v.get("pubdate") or v.get("created")),
                        stats=stats,
                        raw=v,
                    )
                )
        return out

    # ---------- 单作品同步 ----------
    def fetch_post_stats(self, platform: str, post_id: str, account=None) -> dict:
        if self.mode == "real":
            return self._real_post_stats(platform, post_id)
        rnd = random.Random(_seed_id(post_id, "stat"))
        plays = rnd.randint(3000, 800000)
        likes = int(plays * rnd.uniform(0.02, 0.09))
        return {
            "plays": plays,
            "likes": likes,
            "favorites": int(likes * rnd.uniform(0.3, 0.8)),
            "shares": int(likes * rnd.uniform(0.05, 0.2)),
            "comments": int(likes * rnd.uniform(0.02, 0.08)),
            "extra": {"platform_extra": rnd.randint(0, 50)} if platform == "bilibili" else {},
        }

    def _real_post_stats(self, platform: str, post_id: str) -> dict:
        if platform == "douyin":
            data = self._get("/douyin/app/v3/fetch_one_video_v2", {"aweme_id": post_id})
            stat = (((data.get("data") or {}).get("aweme_detail") or {}).get("statistics")) or {}
        elif platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_video_note_detail", {"note_id": post_id})
            note = _note_payload(data) or {}
            # App V2：笔记字段直接平铺（liked_count/comments_count/...），旧 interact_info 兜底
            stat = note.get("interact_info") or {
                "play_count": note.get("pre_view_count"),
                "digg_count": note.get("liked_count") or note.get("likes"),
                "collected_count": note.get("collected_count"),
                "share_count": note.get("share_count"),
                "comment_count": note.get("comments_count"),
            }
        else:  # bilibili 单条详情（View.stat 全量）
            aid = post_id.split(":", 1)[1] if post_id.startswith("aid:") else post_id
            data = self._get("/bilibili/web/fetch_video_detail", {"aid": aid})
            view = ((((data.get("data") or {}).get("data")) or {}).get("View")) or {}
            stat = view.get("stat") or {}
        return {
            "plays": int(stat.get("play_count") or stat.get("view") or 0),
            "likes": int(stat.get("digg_count") or stat.get("liked_count") or stat.get("like") or 0),
            "favorites": int(stat.get("collect_count") or stat.get("collected_count") or stat.get("favorite") or 0),
            "shares": int(stat.get("share_count") or 0),
            "comments": int(stat.get("comment_count") or stat.get("reply") or 0),
            "extra": {
                "danmaku": int(stat.get("danmaku") or 0),
                "coin": int(stat.get("coin") or 0),
            },
        }

    # ---------- 视频下载地址（R-077） ----------
    def fetch_video_source(
        self, platform: str, post_id: str, account=None, prefer_url: str = ""
    ) -> dict | None:
        """解析可下载的视频源（低清优先），无视频/不可下载返回 None。

        返回结构：
        - 抖音/小红书：{"kind": "mp4", "urls": [...]}（单文件含音轨）
        - B站：{"kind": "dash", "video_url": ..., "audio_url": ...}（需 ffmpeg 合并）
        mock 模式或无真实地址返回 None（不下载、不编造）。
        """
        if self.mode != "real":
            return None
        try:
            if platform == "douyin":
                return self._douyin_video_source(post_id, prefer_url)
            if platform == "xiaohongshu":
                return self._xiaohongshu_video_source(post_id)
            if platform == "bilibili":
                return self._bilibili_video_source(post_id)
        except TikHubError:
            return None
        return None

    def _douyin_video_source(self, post_id: str, prefer_url: str = "") -> dict | None:
        # 低清优先：bit_rate 升序里挑有地址的最低档；再补默认 play_addr / 已存直链
        urls: list[str] = []
        seen: set[str] = set()

        def _add(u: str) -> None:
            if u and u not in seen:
                seen.add(u)
                urls.append(u)

        if prefer_url:
            _add(prefer_url)
        data = self._get("/douyin/app/v3/fetch_one_video_v2", {"aweme_id": post_id})
        video = ((data.get("data") or {}).get("aweme_detail") or {}).get("video") or {}
        default = _first_url((video.get("play_addr") or {}).get("url_list") or [])
        try:
            bit_rates = sorted(
                (video.get("bit_rate") or []),
                key=lambda br: int(br.get("bit_rate") or 0) or 10**9,
            )
        except (TypeError, ValueError):
            bit_rates = video.get("bit_rate") or []
        for br in bit_rates:
            _add(_first_url(((br.get("play_addr") or {}).get("url_list")) or []))
        if default:
            _add(default)
        return {"kind": "mp4", "urls": urls} if urls else None

    def _xiaohongshu_video_source(self, post_id: str) -> dict | None:
        data = self._get("/xiaohongshu/app_v2/get_video_note_detail", {"note_id": post_id})
        note = _note_payload(data)
        if not note:
            return None
        media = ((note.get("video_info_v2") or {}).get("media")) or {}
        stream = media.get("stream") or {}
        # 优先 h264（兼容性最好），其次 h265/h266/av1；同组内挑最低码率那档
        for codec in ("h264", "h265", "h266", "av1"):
            items = [it for it in (stream.get(codec) or []) if it.get("master_url")]
            if not items:
                continue
            best = min(items, key=lambda it: int(it.get("video_bitrate") or 0) or 10**9)
            urls: list[str] = []

            def _https(u: str) -> str:
                return u if u.startswith("https://") else "https://" + u[len("http://"):]

            urls.append(_https(best["master_url"]))
            for bu in (best.get("backup_urls") or [])[:3]:
                if bu:
                    urls.append(_https(bu))
            return {"kind": "mp4", "urls": urls}
        return None

    def _bilibili_video_source(self, post_id: str) -> dict | None:
        aid = post_id.split(":", 1)[1] if post_id.startswith("aid:") else post_id
        detail = self._get("/bilibili/web/fetch_video_detail", {"aid": aid})
        view = (((detail.get("data") or {}).get("data")) or {}).get("View") or {}
        pages = view.get("pages") or []
        cid = (pages[0] or {}).get("cid") or 0
        if not cid:
            return None
        bvid = view.get("bvid") or ""
        # TikHub SDK 签名：fetch_video_playurl(bv_id, cid)；端点在线上不可用时 404 → 抛错返回 None
        play = self._get(
            "/bilibili/web/fetch_video_playurl",
            {"bv_id": bvid, "cid": cid},
        )
        inner = (play.get("data") or {}).get("data") or play.get("data") or {}
        dash = inner.get("dash") or {}
        vitems = dash.get("video") or []
        aitems = dash.get("audio") or []

        def _pick(items) -> str:
            best = ""
            for it in sorted(items, key=lambda x: int(x.get("id") or 10**9)):
                u = _first_media_url(it)
                if u:
                    best = u
                    break
            return best

        vurl = _pick(vitems)
        aurl = _pick(aitems)
        if vurl and aurl:
            return {"kind": "dash", "video_url": vurl, "audio_url": aurl}
        durls = inner.get("durl") or []
        if durls:
            return {"kind": "mp4", "urls": [d.get("url") for d in durls if d.get("url")]}
        return None

    # ---------- 评论（R-028 选题池 / R-067 点赞 Top50 入库） ----------
    def fetch_comments(self, platform: str, post_id: str, count: int = 20, account=None, raw: dict | None = None) -> list[CommentData]:
        """拉取评论（含点赞数/昵称）。mock 返回确定性造数；real 尽力解析各平台字段。"""
        if self.mode == "real":
            return self._real_comments(platform, post_id, max(3, count), raw)
        return self._mock_comments(platform, post_id, max(3, count))

    def _mock_comments(self, platform: str, post_id: str, count: int) -> list[CommentData]:
        rnd = random.Random(_seed_id(post_id, "comments"))
        pool = _COMMENT_POOL[:]
        out: list[CommentData] = []
        seq = 0
        # 需要超过池子条数（如 Top50 验收）时，用确定性后缀补足唯一评论
        while len(out) < count:
            for base in pool:
                if len(out) >= count:
                    break
                if seq == 0:
                    text = base
                else:
                    text = f"{base}（追问{seq}）"
                likes = int(rnd.random() ** 2 * 3000) + seq * 7
                out.append(
                    CommentData(
                        text=text,
                        likes=likes,
                        user_nick=f"用户{rnd.randint(1000, 9999)}",
                    )
                )
            seq += 1
        return out

    def _real_comments(self, platform: str, post_id: str, count: int, raw: dict | None = None) -> list[CommentData]:
        out: list[CommentData] = []
        if platform == "douyin":
            data = self._get("/douyin/app/v3/fetch_video_comments", {"aweme_id": post_id, "count": min(count, 50)})
            for c in ((data.get("data") or {}).get("comments") or []):
                txt = ((c.get("text") or "") or "").strip()
                if not txt:
                    continue
                out.append(
                    CommentData(
                        text=txt,
                        likes=int(c.get("digg_count") or c.get("like_count") or 0),
                        user_nick=(((c.get("user") or {}).get("nickname")) or "")[:100],
                    )
                )
        elif platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_note_comments", {"note_id": post_id, "cursor": ""})
            inner = ((data.get("data") or {}).get("data")) or {}
            for c in (inner.get("comments") or []):
                txt = (c.get("content") or "").strip()
                if not txt:
                    continue
                out.append(
                    CommentData(
                        text=txt,
                        likes=int(c.get("like_count") or c.get("likes") or 0),
                        user_nick=(((c.get("user_info") or {}).get("nickname")) or "")[:100],
                    )
                )
        else:
            bvid = (raw or {}).get("bvid") or (post_id.split(":", 1)[1] if post_id.startswith("bvid:") else "")
            if bvid:
                data = self._get("/bilibili/web/fetch_video_comments", {"bv_id": bvid})
                inner = (data.get("data") or {}).get("data") or data.get("data") or {}
                for c in (inner.get("replies") or []):
                    txt = (((c.get("content") or {}).get("message")) or "").strip()
                    if not txt:
                        continue
                    out.append(
                        CommentData(
                            text=txt,
                            likes=int(c.get("like") or 0),
                            user_nick=(((c.get("member") or {}).get("uname")) or "")[:100],
                        )
                    )
        return out[:count]


def _ts(value) -> datetime | None:
    """平台时间戳(epoch秒, UTC) → 北京时间 naive datetime（前端按 Asia/Shanghai 展示）。"""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


# R-241：进程级复用 TikHubClient（按 mode/base_url/api_key）。共享后 requests_used 为
# **线程内累计值**：计费方按「同一线程内调用前后差值」实现（douyin_creator_sync._charge_requests
# / douyin_references 均已核对），并发消费者各自精确、不会互相污染预算。
# mock 模式复用无副作用（mock 分支不发请求）。
_CLIENT_CACHE: dict[tuple[str, str, str], TikHubClient] = {}
_CLIENT_CACHE_LOCK = threading.Lock()


def make_client(mode: str = "") -> TikHubClient:
    """取进程级共享的 TikHubClient（R-241）。同一个 (mode, base_url, api_key) 只建一次。"""
    settings = get_settings()
    resolved_mode = (mode or settings.tikhub_mode or "mock").strip().lower()
    key = (
        resolved_mode,
        (settings.tikhub_base_url or "").rstrip("/"),
        settings.tikhub_api_key or "",
    )
    with _CLIENT_CACHE_LOCK:
        cached = _CLIENT_CACHE.get(key)
        if cached is not None:
            return cached
        client = TikHubClient(mode=mode)
        _CLIENT_CACHE[key] = client
        return client
