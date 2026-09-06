"""热点挖掘适配器：mock（开发/测试）或抖音/B站/小红书真实抓取。

真实抓取依赖公开/非官方接口，可能随平台改版失效；每个适配器独立 try/except，
单个平台失败不影响其他平台（降级设计）。首次接入请在 NAS（有外网）上联调。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import httpx

from ..config import get_settings
from ..core.pipeline import today_key
from ..models.hot_topic import HotTopic


@dataclass
class HotItem:
    platform: str
    title: str
    heat: str = ""
    url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class BaseHotSource:
    name = "base"

    def fetch(self) -> list[HotItem]:
        raise NotImplementedError


class MockHotSource(BaseHotSource):
    """开发/测试用确定性热点。"""

    name = "mock"

    def fetch(self) -> list[HotItem]:
        pool = [
            ("douyin", "大厂秋招缩编，应届生该先就业还是再等等"),
            ("douyin", "月薪 8 千和 1 万五的 offer 怎么选"),
            ("douyin", "裸辞一年后我后悔了吗"),
            ("douyin", "35 岁转行还来得及吗"),
            ("douyin", "面试被问离职原因，怎么答不扣分"),
            ("douyin", "简历上哪些词一写就废"),
            ("douyin", "HR 筛简历 10 秒看什么"),
            ("douyin", "谈薪时说这句话，直接少拿两千"),
            ("bilibili", "程序员 35 岁危机是伪命题吗"),
            ("bilibili", "副业月入过万的真实成本"),
            ("bilibili", "知识博主日更 30 天的变化"),
            ("bilibili", "转行程序员一年后我后悔了吗"),
            ("bilibili", "为什么你面试总挂在同一轮"),
            ("bilibili", "普通人 3 个月学会一项能赚钱的技能"),
            ("bilibili", "上班摸鱼搞副业，被发现了怎么办"),
            ("bilibili", "用 AI 写脚本前，先搞懂这 3 件事"),
            ("xiaohongshu", "应届生第一份工作：大厂还是小厂"),
            ("xiaohongshu", "谈薪时最不该说的一句话"),
            ("xiaohongshu", "面试被问职业规划怎么答不扣分"),
            ("xiaohongshu", "下班副业从哪开始：先做这 3 件事"),
            ("xiaohongshu", "简历别造假，但要学会'会写'"),
            ("xiaohongshu", "文科生能转的 6 个高薪方向"),
            ("xiaohongshu", "打工人时间管理：下班后 2 小时怎么用"),
            ("xiaohongshu", "搞副业先别辞职，除非你算清这笔账"),
            ("douyin", "AI 正在取代哪些岗位，别慌先看这个"),
            ("douyin", "为什么你的内容没人看：选题在作祟"),
            ("bilibili", "口播脚本怎么写得像说话，而不是像作文"),
            ("xiaohongshu", "普通人做自媒体的第一个月怎么熬"),
        ]
        return [HotItem(plat, title, "热", "https://example.com/hot") for plat, title in pool]


class BilibiliHotSource(BaseHotSource):
    name = "bilibili"

    def fetch(self) -> list[HotItem]:
        with httpx.Client(timeout=15) as client:
            resp = client.get("https://api.bilibili.com/x/web-interface/popular?ps=20")
            resp.raise_for_status()
            data = resp.json()
        items = []
        for row in (data.get("data") or {}).get("list") or []:
            items.append(
                HotItem(
                    platform="bilibili",
                    title=row.get("title", ""),
                    heat=str(row.get("stat", {}).get("view", "")),
                    url=row.get("short_link_v2") or "",
                )
            )
        return [i for i in items if i.title]


class DouyinHotSource(BaseHotSource):
    """抖音热榜：公开 web 接口，可能随改版失效；失败由上层捕获降级。"""

    name = "douyin"

    def fetch(self) -> list[HotItem]:
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
        }
        with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(
                "https://www.douyin.com/aweme/v1/web/hot/search/list/", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        items = []
        word_list = (data.get("data") or {}).get("word_list") or []
        for row in word_list:
            items.append(
                HotItem(
                    platform="douyin",
                    title=row.get("word", ""),
                    heat=str(row.get("hot_value", "")),
                )
            )
        return [i for i in items if i.title]


class XiaohongshuHotSource(BaseHotSource):
    """小红书热搜：接口不稳定，尽力抓取；失败降级为空。"""

    name = "xiaohongshu"

    def fetch(self) -> list[HotItem]:
        with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get("https://www.xiaohongshu.com/api/sns/web/v1/hot_search")
            resp.raise_for_status()
            data = resp.json()
        items = []
        for row in ((data.get("data") or {}).get("items")) or []:
            items.append(
                HotItem(
                    platform="xiaohongshu",
                    title=row.get("word", ""),
                    heat=str(row.get("hot_value", "")),
                )
            )
        return [i for i in items if i.title]


class TikHubHotSource(BaseHotSource):
    """经 TikHub 拉真实热搜（有 ECHO_TIKHUB_API_KEY 时优先，单平台失败不影响整体）。"""

    platform = ""
    api_path = ""

    def __init__(self, settings=None):
        settings = settings or get_settings()
        self._key = settings.tikhub_api_key
        self._base = (settings.tikhub_base_url or "https://api.tikhub.io/api/v1").rstrip("/")

    def _get(self, path: str, params: dict | None = None) -> dict:
        with httpx.Client(
            timeout=20, headers={"Authorization": f"Bearer {self._key}"}
        ) as client:
            resp = client.get(f"{self._base}{path}", params=params or {})
            resp.raise_for_status()
            return resp.json()


class DouyinTikHubHotSource(TikHubHotSource):
    """抖音热搜榜（App V3）。data.data.word_list[] -> word / hot_value。"""

    platform = "douyin"
    api_path = "/douyin/app/v3/fetch_hot_search_list"

    def fetch(self) -> list[HotItem]:
        d = self._get(self.api_path)
        rows = ((d.get("data") or {}).get("data") or {}).get("word_list") or []
        out = []
        for r in rows:
            title = (r.get("word") or "").strip()
            if title:
                out.append(HotItem("douyin", title, str(r.get("hot_value") or "")))
        return out


class BilibiliTikHubHotSource(TikHubHotSource):
    """B站热搜榜（Web）。data.data.trending.list[] -> show_name / keyword / heat_score。"""

    platform = "bilibili"
    api_path = "/bilibili/web/fetch_hot_search"

    def fetch(self) -> list[HotItem]:
        d = self._get(self.api_path, {"limit": 50})
        rows = ((((d.get("data") or {}).get("data") or {}).get("trending") or {}).get("list")) or []
        out = []
        for r in rows:
            title = (r.get("show_name") or r.get("keyword") or "").strip()
            if title:
                out.append(HotItem("bilibili", title, str(r.get("heat_score") or "")))
        return out


class XiaohongshuTikHubHotSource(TikHubHotSource):
    """小红书无公开热搜榜，用平台搜索联想词代表“大众在搜什么”（web_v3 fetch_search_suggest）。"""

    platform = "xiaohongshu"
    api_path = "/xiaohongshu/web_v3/fetch_search_suggest"
    seeds = ["求职", "面试", "副业", "职场", "简历", "大学生"]

    def fetch(self) -> list[HotItem]:
        out: list[HotItem] = []
        seen: set[str] = set()
        for kw in self.seeds:
            try:
                d = self._get(self.api_path, {"keyword": kw})
            except Exception:  # noqa: BLE001 单关键词失败不影响
                continue
            rows = ((d.get("data") or {}).get("data") or {}).get("sug_items") or []
            for r in rows:
                title = (r.get("text") or "").strip()
                if title and title not in seen:
                    seen.add(title)
                    out.append(HotItem("xiaohongshu", title, ""))
        return out


def get_sources(settings=None) -> list[BaseHotSource]:
    settings = settings or get_settings()
    mode = (settings.hot_source_mode or "mock").strip().lower()
    if mode == "mock":
        return [MockHotSource()]
    # real：优先 TikHub（配置了 key 时），否则退回各平台公开接口
    if settings.tikhub_api_key:
        return [
            DouyinTikHubHotSource(settings),
            BilibiliTikHubHotSource(settings),
            XiaohongshuTikHubHotSource(settings),
        ]
    return [DouyinHotSource(), BilibiliHotSource(), XiaohongshuHotSource()]


def fetch_and_store(db, settings=None) -> list[HotItem]:
    """抓取并入库（按 平台+标题+日期 去重），返回全部热点。"""
    settings = settings or get_settings()
    key = today_key()
    collected: list[HotItem] = []
    for source in get_sources(settings):
        try:
            items = source.fetch()
        except Exception:  # noqa: BLE001  单个平台失败不影响整体
            continue
        for item in items:
            exists = (
                db.query(HotTopic)
                .filter(
                    HotTopic.platform == item.platform,
                    HotTopic.title == item.title,
                    HotTopic.topic_date == key,
                )
                .first()
            )
            if exists is None:
                db.add(
                    HotTopic(
                        platform=item.platform,
                        title=item.title,
                        heat=item.heat,
                        url=item.url,
                        topic_date=key,
                    )
                )
                collected.append(item)
            else:
                collected.append(item)
    db.commit()
    return collected
