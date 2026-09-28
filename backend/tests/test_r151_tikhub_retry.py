"""R-151：TikHub 请求重试 + 单路由限速测试。

覆盖验收标准（全部离线，不发真实请求）：
- SSL EOF / 连接重置这类瞬时故障 → 自动重试，重试成功则返回数据；
- HTTP 429（TikHub 单路由限速 1 req/s）→ 自动重试；
- 其它 4xx（参数/权限类永久错误）→ 不重试，立即抛 TikHubError；
- 重试耗尽 → 抛 TikHubError，尝试次数 = `_MAX_ATTEMPTS`，消息里带「已重试 N 次」；
- 同路由排队：同一 path 连续两次调用会等待，不同 path 互不阻塞。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from app.services.platform import tikhub
from app.services.platform.tikhub import TikHubClient, TikHubError

_SSL_EOF = "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1082)"


@pytest.fixture()
def client():
    return TikHubClient(mode="real", api_key="k", base_url="http://x")


@pytest.fixture()
def no_sleep(monkeypatch):
    """记录退避秒数（不真等），并关掉路由排队，保证用例毫秒级跑完。

    R-163：全局令牌桶为进程级单例，用例间会累计消耗；每个用例开始重置，避免相互干扰。
    """
    slept: list[float] = []
    monkeypatch.setattr(tikhub.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(tikhub, "_ROUTE_MIN_INTERVAL", 0.0)
    tikhub._reset_limiter()
    monkeypatch.setattr(tikhub, "_ROUTE_LAST", {})
    return slept


def _patch_get(monkeypatch, outcomes):
    """按调用顺序返回预设结果：Exception 实例则抛出，Response 则返回。"""
    calls: list[str] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        item = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(tikhub.httpx, "get", fake_get)
    return calls


def test_ssl_eof_is_retried_then_succeeds(client, no_sleep, monkeypatch):
    calls = _patch_get(
        monkeypatch,
        [
            httpx.ConnectError(_SSL_EOF),
            httpx.ConnectError(_SSL_EOF),
            httpx.Response(200, json={"code": 200, "data": {"ok": True}}),
        ],
    )
    data = client._get("/douyin/app/v3/fetch_video_comments", {"aweme_id": "1"})
    assert data["data"]["ok"] is True
    assert len(calls) == 3
    assert no_sleep == [1.5, 4.0]  # 退避 1.5s → 4.0s


def test_http_429_is_retried_then_succeeds(client, no_sleep, monkeypatch):
    calls = _patch_get(
        monkeypatch,
        [
            httpx.Response(429, text='{"detail":{"message":"Request too fast, the request rate limit for the current route is 1 times/second"}}'),
            httpx.Response(200, json={"code": 200}),
        ],
    )
    assert client._get("/douyin/app/v3/fetch_video_comments")["code"] == 200
    assert len(calls) == 2
    # R-163：429 除退避重试外，还会抬高该路由下次允许时间（按路由兜底），故总 sleep 不止一次
    assert no_sleep[0] == 1.5


def test_permanent_4xx_is_not_retried(client, no_sleep, monkeypatch):
    calls = _patch_get(monkeypatch, [httpx.Response(400, text="bad request")])
    with pytest.raises(TikHubError) as ei:
        client._get("/bilibili/web/fetch_video_detail", {"aid": "1"})
    assert "HTTP 400" in str(ei.value)
    assert "已重试" not in str(ei.value)
    assert len(calls) == 1
    assert no_sleep == []  # 永久错误不等待


def test_retry_exhausted_raises_with_attempts(client, no_sleep, monkeypatch):
    calls = _patch_get(monkeypatch, [httpx.ConnectError(_SSL_EOF)])
    with pytest.raises(TikHubError) as ei:
        client._get("/xiaohongshu/app_v2/get_video_note_detail", {"note_id": "x"})
    assert "已重试 3 次" in str(ei.value)
    assert "UNEXPECTED_EOF" in str(ei.value)
    assert len(calls) == 4
    assert client.requests_used == 4
    assert no_sleep == [1.5, 4.0, 8.0]


def test_without_api_key_raises_before_any_request(monkeypatch):
    monkeypatch.setattr(tikhub.httpx, "get", lambda *a, **k: pytest.fail("不应发起请求"))
    client = TikHubClient(mode="real", api_key="k", base_url="http://x")
    client.api_key = ""  # 显式清空：验证「无 key 不发请求」护栏
    with pytest.raises(TikHubError, match="ECHO_TIKHUB_API_KEY"):
        client._get("/tikhub/user/get_user_info")


def test_throttle_spaces_same_route_only(monkeypatch):
    """同一 path 第二次调用要排队；不同 path 不互相阻塞。"""
    slept: list[float] = []
    monkeypatch.setattr(tikhub.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(tikhub, "_ROUTE_MIN_INTERVAL", 0.3)
    monkeypatch.setattr(tikhub, "_ROUTE_LAST", {})

    tikhub._throttle_route("/a")  # 首次：不等待
    assert slept == []
    tikhub._throttle_route("/a")  # 同路由：等待 ~0.3s
    assert len(slept) == 1 and 0.25 < slept[0] <= 0.35
    tikhub._throttle_route("/b")  # 不同路由：不等待
    assert len(slept) == 1
