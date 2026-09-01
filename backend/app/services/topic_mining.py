"""热点挖掘适配器：mock（开发/测试）或抖音/B站/小红书真实抓取。

真实抓取依赖公开/非官方接口，可能随平台改版失效；每个适配器独立 try/except，
单个平台失败不影响其他平台（降级设计）。首次接入请在 NAS（有外网）上联调。
"""
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
        return [
            HotItem("douyin", "2026 年最难求职季，应届生怎么办"),
            HotItem("bilibili", "面试官最反感的 5 个回答，别再踩坑"),
            HotItem("xiaohongshu", "普通人如何靠副业月入过万？"),
            HotItem("douyin", "AI 正在取代哪些岗位？",
                    "热", "https://example.com/ai-jobs"),
        ]


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


def get_sources(settings=None) -> list[BaseHotSource]:
    settings = settings or get_settings()
    mode = (settings.hot_source_mode or "mock").strip().lower()
    if mode == "mock":
        return [MockHotSource()]
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
