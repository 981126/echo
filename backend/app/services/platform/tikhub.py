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
    followers: int = 0
    likes_total: int = 0
    posts_total: int = 0
    following: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


def parse_link(platform: str, link: str) -> str:
    """从主页分享链接解析平台用户 ID（real 模式尽力而为；mock 从链接尾串解析）。"""
    link = (link or "").strip()
    if not link:
        return ""
    if platform == "bilibili":
        marker = "space.bilibili.com/"
        idx = link.find(marker)
        if idx >= 0:
            tail = link[idx + len(marker):].split("/")[0].split("?")[0]
            return tail if tail.isdigit() else ""
        return ""
    if platform == "xiaohongshu":
        marker = "userId="
        idx = link.find(marker)
        if idx >= 0:
            return link[idx + len(marker):].split("&")[0].strip()
        # xhslink 短链在 mock 中无法解析，直接截取尾串作占位
        return link.rstrip("/").split("/")[-1].split("?")[0][:32]
    if platform == "douyin":
        marker = "douyin.com/user/"
        idx = link.find(marker)
        if idx >= 0:
            return link[idx + len(marker):].split("?")[0].strip()
        # 短链：mock 占位
        return link.rstrip("/").split("/")[-1].split("?")[0][:64]
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
            return ProfileData(
                nickname=user.get("nickname", ""),
                followers=int(user.get("follower_count") or 0),
                likes_total=int(user.get("total_favorited") or 0),
                posts_total=int(user.get("aweme_count") or 0),
                following=int(user.get("following_count") or 0),
                raw=data,
            )
        if platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_user_info", {"user_id": user_id})
            d = data.get("data") or {}
            return ProfileData(
                nickname=d.get("nickname", ""),
                followers=int(d.get("follower_count") or 0),
                likes_total=int(d.get("likes_count") or 0),
                posts_total=int(d.get("note_count") or 0),
                following=int(d.get("following_count") or 0),
                raw=data,
            )
        # bilibili web：uid 直接取用户空间页公开信息（best-effort）
        data = self._get("/bilibili/web/fetch_user_info", {"uid": user_id})
        d = data.get("data") or {}
        return ProfileData(
            nickname=d.get("name", ""),
            followers=int(d.get("follower") or 0),
            likes_total=int(d.get("likes") or 0),
            posts_total=int(d.get("video") or 0),
            following=int(d.get("following") or 0),
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
            notes = (data.get("data") or {}).get("notes") or []
            for n in notes[:count]:
                stat = n.get("interact_info") or {}
                cover = (((n.get("image_list") or [{}])[0]).get("url") or "")
                out.append(
                    PostData(
                        platform_post_id=str(n.get("note_id") or ""),
                        title=(n.get("title") or "")[:200],
                        desc=n.get("desc") or "",
                        cover_url=cover,
                        video_url="",
                        publish_time=_ts(n.get("time")),
                        stats={
                            "plays": int(stat.get("viewed_count") or 0),
                            "likes": int(stat.get("liked_count") or 0),
                            "favorites": int(stat.get("collected_count") or 0),
                            "shares": int(stat.get("share_count") or 0),
                            "comments": int(stat.get("comment_count") or 0),
                            "extra": {},
                        },
                        raw=n,
                    )
                )
        else:  # bilibili
            data = self._get("/bilibili/web/fetch_user_post_videos_v2", {"uid": user_id, "page_num": 1, "page_size": min(count, 30)})
            vlist = (data.get("data") or {}).get("list") or (data.get("data") or {}).get("vlist") or []
            for v in vlist[:count]:
                stat = v.get("stat") or {}
                out.append(
                    PostData(
                        platform_post_id=f"bvid:{v.get('bvid') or ''}",
                        title=v.get("title") or "",
                        desc=v.get("title") or "",
                        cover_url=v.get("pic") or "",
                        video_url="",
                        publish_time=_ts(v.get("created")),
                        stats={
                            "plays": int(stat.get("view") or 0),
                            "likes": int(stat.get("like") or 0),
                            "favorites": int(stat.get("favorite") or 0),
                            "shares": int(stat.get("share") or 0),
                            "comments": int(stat.get("reply") or 0),
                            "extra": {"danmaku": int(stat.get("danmaku") or 0), "coin": int(stat.get("coin") or 0)},
                        },
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
        else:
            bvid = post_id.split(":", 1)[1] if post_id.startswith("bvid:") else post_id
            data = self._get("/bilibili/web/fetch_video_info", {"bvid": bvid})
            stat = ((data.get("data") or {}).get("stat")) or {}
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
    def fetch_comments(self, platform: str, post_id: str, count: int = 20, account=None) -> list[str]:
        if self.mode == "real":
            return self._real_comments(platform, post_id)
        rnd = random.Random(_seed_id(post_id, "comments"))
        pool = _COMMENT_POOL[:]
        rnd.shuffle(pool)
        return pool[: max(3, count)]

    def _real_comments(self, platform: str, post_id: str) -> list[str]:
        texts: list[str] = []
        if platform == "douyin":
            data = self._get("/douyin/app/v3/fetch_video_comments", {"aweme_id": post_id, "count": 20})
            for c in ((data.get("data") or {}).get("comments") or []):
                txt = ((c.get("text") or "") or "").strip()
                if txt:
                    texts.append(txt)
        elif platform == "xiaohongshu":
            data = self._get("/xiaohongshu/app_v2/get_note_comments", {"note_id": post_id, "cursor": ""})
            for c in ((data.get("data") or {}).get("comments") or []):
                txt = (c.get("content") or "").strip()
                if txt:
                    texts.append(txt)
        else:
            bvid = post_id.split(":", 1)[1] if post_id.startswith("bvid:") else post_id
            data = self._get("/bilibili/web/fetch_video_comments", {"bvid": bvid})
            for c in ((data.get("data") or {}).get("replies") or []):
                txt = (c.get("content") or {}).get("message", "").strip()
                if txt:
                    texts.append(txt)
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
