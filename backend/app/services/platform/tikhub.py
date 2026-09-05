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
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from ...config import get_settings

PLATFORMS = ["douyin", "xiaohongshu", "bilibili"]
PLATFORM_LABEL = {"douyin": "抖音", "xiaohongshu": "小红书", "bilibili": "B站"}

# 主页链接解析规则：platform -> (正则组名/顺序)
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


def _seed_id(user_id: str, salt: str = "") -> int:
    return int(hashlib.md5(f"{user_id}:{salt}".encode()).hexdigest(), 16)


def parse_post_id(link: str) -> tuple[str, str]:
    """从作品分享链接解析 (platform, 作品ID)。支持抖音/B站/小红书常见形态。"""
    link = (link or "").strip()
    if not link:
        return "", ""
    low = link.lower()
    if "bilibili.com/video/" in low:
        marker = "/video/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("bilibili", f"bvid:{tail}") if tail else ("", "")
    if "douyin.com/video/" in low:
        marker = "/video/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("douyin", tail) if tail else ("", "")
    if "xiaohongshu.com/explore/" in low:
        marker = "/explore/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("xiaohongshu", tail) if tail else ("", "")
    if "xiaohongshu.com/discovery/item/" in low:
        marker = "/discovery/item/"
        idx = low.find(marker)
        tail = link[idx + len(marker):].split("?")[0].split("/")[0]
        return ("xiaohongshu", tail) if tail else ("", "")
    return "", ""


class TikHubError(RuntimeError):
    pass


@dataclass
class PostData:
    platform_post_id: str
    title: str = ""
    desc: str = ""
    cover_url: str = ""
    video_url: str = ""
    publish_time: datetime | None = None
    stats: dict[str, Any] = field(default_factory=dict)  # plays/likes/favorites/shares/comments/extra
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProfileData:
    nickname: str = ""
    avatar_url: str = ""
    followers: int = 0
    likes_total: int = 0
    posts_total: int = 0
    following: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


_SHORT_HOSTS = ("v.douyin.com", "xhslink.com", "b23.tv", "douyin.com", "xiaohongshu.com", "bilibili.com")


def _resolve_redirect(link: str) -> str:
    """分享短链解析：跟随重定向拿到真实主页 URL（失败返回原链接）。"""
    low = (link or "").lower()
    if not low.startswith(("http://", "https://")):
        return link
    if not any(h in low for h in _SHORT_HOSTS):
        return link
    try:
        resp = httpx.get(link, follow_redirects=True, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        return str(resp.url)
    except Exception:  # noqa: BLE001 无法联网/超时时原样返回，走本地规则
        return link


def _extract_after(link: str, marker: str) -> str:
    idx = link.find(marker)
    if idx < 0:
        return ""
    tail = link[idx + len(marker):]
    # 截断到 路径段结束 / ? # 空白
    out = ""
    for ch in tail:
        if ch in "/?# \t\r\n":
            break
        out += ch
    return out.strip()


def parse_link(platform: str, link: str) -> str:
    """从主页分享链接解析平台用户 ID。

    规则：先按完整 URL 结构解析；识别不了短链域名时跟随重定向后再解析；
    解析不出合法 ID 一律返回空（不返回乱码尾巴，避免存错 ID）。
    """
    link = _resolve_redirect((link or "").strip())
    if not link:
        return ""
    low = link.lower()
    if platform == "bilibili":
        marker = "space.bilibili.com/"
        if marker in low:
            tail = _extract_after(link, marker)
            return tail if tail.isdigit() else ""
        return ""
    if platform == "xiaohongshu":
        # 两种形态：/user/profile?userId=xxx 与 /user/profile/xxx
        if "userid=" in low:
            return _extract_after(link.split("userId=", 1)[1].split("&")[0], "")
        for marker in ("/user/profile/", "/user/"):
            if marker in low:
                uid = _extract_after(link, marker)
                if uid and len(uid) >= 6:
                    return uid
        return ""
    if platform == "douyin":
        marker = "douyin.com/user/"
        if marker in low:
            uid = _extract_after(link, marker)
            # sec_user_id 允许字母数字与 _- 等，但不能带 .html 之类
            if uid and not uid.lower().endswith((".html", ".do")):
                return uid
        # v.douyin.com 已重定向仍失败时
        return ""
    return ""


class TikHubClient:
    """三平台统一客户端。mock 返回确定性数据；real 走 REST（无 key 时抛错）。"""

    def __init__(self, mode: str = "", api_key: str = "", base_url: str = ""):
        settings = get_settings()
        self.mode = (mode or settings.tikhub_mode or "mock").strip().lower()
        self.api_key = api_key or settings.tikhub_api_key
        self.base_url = (base_url or settings.tikhub_base_url).rstrip("/")
        self._requests = 0

    @property
    def requests_used(self) -> int:
        return self._requests

    # ---------- 内部 ----------
    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.api_key:
            raise TikHubError("未配置 ECHO_TIKHUB_API_KEY（real 模式需要）")
        self._requests += 1
        try:
            resp = httpx.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise TikHubError(f"TikHub 请求失败: {exc}") from exc

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
        is_bench = getattr(account, "sync_frequency", "") == "weekly" if account else False
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
            return self._real_posts(platform, user_id, count)
        return self._mock_posts(platform, user_id, count, account)

    def _mock_posts(self, platform: str, user_id: str, count: int, account=None) -> list[PostData]:
        rnd = random.Random(_seed_id(user_id, platform))
        pool = _TITLE_POOL.get(platform, _TITLE_POOL["douyin"])
        out: list[PostData] = []
        now = datetime.utcnow()
        for i in range(min(count, 60)):
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
            stat = ((((data.get("data") or {}).get("note") or {}).get("interact_info")) or {})
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

    # ---------- 评论（R-028 选题池） ----------
    def fetch_comments(self, platform: str, post_id: str, count: int = 20, account=None, raw: dict | None = None) -> list[str]:
        if self.mode == "real":
            return self._real_comments(platform, post_id, raw)
        rnd = random.Random(_seed_id(post_id, "comments"))
        pool = _COMMENT_POOL[:]
        rnd.shuffle(pool)
        return pool[: max(3, count)]

    def _real_comments(self, platform: str, post_id: str, raw: dict | None = None) -> list[str]:
        texts: list[str] = []
        if platform == "douyin":
            data = self._get("/douyin/app/v3/fetch_video_comments", {"aweme_id": post_id, "count": 20})
            for c in ((data.get("data") or {}).get("comments") or []):
                txt = ((c.get("text") or "") or "").strip()
                if txt:
                    texts.append(txt)
        elif platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_note_comments", {"note_id": post_id, "cursor": ""})
            inner = ((data.get("data") or {}).get("data")) or {}
            for c in (inner.get("comments") or []):
                txt = (c.get("content") or "").strip()
                if txt:
                    texts.append(txt)
        else:
            bvid = (raw or {}).get("bvid") or (post_id.split(":", 1)[1] if post_id.startswith("bvid:") else "")
            if bvid:
                data = self._get("/bilibili/web/fetch_video_comments", {"bv_id": bvid})
                inner = (data.get("data") or {}).get("data") or data.get("data") or {}
                for c in (inner.get("replies") or []):
                    txt = ((c.get("content") or {}).get("message")) or ""
                    if txt and txt.strip():
                        texts.append(txt.strip())
        return texts[:20]


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def make_client(mode: str = "") -> TikHubClient:
    return TikHubClient(mode=mode)
