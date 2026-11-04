"""R-246：TikHub 连接池稳定性回归测试。

覆盖：
- `get_client` 的 trust_env 缓存键 + `reset_client` 重建；
- TikHub 默认直连、`ECHO_TIKHUB_USE_PROXY` 开关生效；
- `PoolTimeout` → 重置共享连接池后用新池重试成功（自愈）；
- `PoolTimeout` 重试耗尽 → 仍按既有语义失败（重置只触发 1 次）；
- 全局并发上限（同时在途 ≤ 配置值）；
- mock 模式不建 HTTP Client、不占并发槽位（行为不变）。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pytest

from app.core import http as core_http
from app.services.platform import tikhub
from app.services.platform.tikhub import TikHubClient, TikHubError


@pytest.fixture()
def client():
    return TikHubClient(mode="real", api_key="k", base_url="http://x")


@pytest.fixture()
def no_sleep(monkeypatch):
    """记录退避秒数（不真等），并重置令牌桶/路由状态，保证用例毫秒级跑完。"""
    slept: list[float] = []
    monkeypatch.setattr(tikhub.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(tikhub, "_ROUTE_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(tikhub, "_ROUTE_LAST", {})
    tikhub._reset_limiter()
    yield slept
    tikhub._reset_limiter()


class _FakeResponse:
    status_code = 200
    text = ""

    def json(self) -> dict:
        return {"code": 200, "ok": True}


def test_get_client_trust_env_cache_key_and_reset():
    core_http.close_all()
    try:
        direct = core_http.get_client("https://example.invalid", trust_env=False)
        proxy = core_http.get_client("https://example.invalid", trust_env=True)
        assert direct is not proxy  # trust_env 不同 → 不同 Client
        assert core_http.get_client("https://example.invalid", trust_env=False) is direct

        assert core_http.reset_client("https://example.invalid", trust_env=False) is True
        fresh = core_http.get_client("https://example.invalid", trust_env=False)
        assert fresh is not direct  # 重置后重建新 Client/连接池
        assert core_http.reset_client("https://example.invalid", trust_env=False, follow_redirects=True) is False
    finally:
        core_http.close_all()


def test_tikhub_http_direct_by_default_and_proxy_switch(monkeypatch):
    calls: list[dict] = []

    def fake_get_client(base_url: str = "", **kwargs) -> object:  # noqa: ANN003
        calls.append({"base_url": base_url, **kwargs})
        return object()

    monkeypatch.setattr(core_http, "get_client", fake_get_client)

    client = TikHubClient(mode="real", api_key="k", base_url="http://x")
    monkeypatch.setattr(tikhub, "get_settings", lambda: SimpleNamespace(tikhub_use_proxy=False))
    client._http()
    assert calls[-1]["trust_env"] is False  # 默认直连

    client._http()
    monkeypatch.setattr(tikhub, "get_settings", lambda: SimpleNamespace(tikhub_use_proxy=True))
    client._http()
    assert calls[-1]["trust_env"] is True  # ECHO_TIKHUB_USE_PROXY=1 → 跟随系统/环境代理


def test_pool_timeout_resets_shared_pool_then_retries(client, no_sleep, monkeypatch):
    calls = {"n": 0}
    resets: list[tuple[str, bool]] = []

    class FakeClient:
        def get(self, url, params=None, headers=None):  # noqa: ANN001, ANN201, ARG002
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.PoolTimeout("timed out")
            return _FakeResponse()

    monkeypatch.setattr(client, "_http", lambda: FakeClient())
    monkeypatch.setattr(tikhub, "_reset_shared_pool", lambda base_url, use_proxy: resets.append((base_url, use_proxy)) or True)

    data = client._get("/douyin/app/v3/fetch_video_comments", {"aweme_id": "1"})
    assert data["code"] == 200
    assert calls["n"] == 2
    assert resets == [("http://x", False)]
    assert no_sleep == [1.5]  # 第 1 次失败后按既有退避等待


def test_pool_timeout_exhausted_keeps_existing_error(client, no_sleep, monkeypatch):
    calls = {"n": 0}
    resets: list[tuple[str, bool]] = []

    class FakeClient:
        def get(self, url, params=None, headers=None):  # noqa: ANN001, ANN201, ARG002
            calls["n"] += 1
            raise httpx.PoolTimeout("timed out")

    monkeypatch.setattr(client, "_http", lambda: FakeClient())
    monkeypatch.setattr(tikhub, "_reset_shared_pool", lambda base_url, use_proxy: resets.append((base_url, use_proxy)) or True)

    with pytest.raises(TikHubError) as ei:
        client._get("/douyin/app/v3/fetch_video_comments")
    assert "已重试 3 次" in str(ei.value)
    assert "PoolTimeout" in str(ei.value)
    assert calls["n"] == 4  # 首次 + 3 次重试（重试次数语义不变）
    assert len(resets) == 1  # 每次请求最多重置 1 次


def test_global_concurrency_cap(monkeypatch):
    state = {"current": 0, "peak": 0}
    lock = threading.Lock()

    class SlowClient:
        def get(self, url, params=None, headers=None):  # noqa: ANN001, ANN201, ARG002
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.05)
            with lock:
                state["current"] -= 1
            return _FakeResponse()

    client = TikHubClient(mode="real", api_key="k", base_url="http://x")
    monkeypatch.setattr(client, "_http", lambda: SlowClient())
    monkeypatch.setenv("ECHO_TIKHUB_MAX_CONCURRENCY", "2")
    get_settings = tikhub.get_settings
    try:
        get_settings.cache_clear()
        tikhub._reset_limiter()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                client._get("/douyin/app/v3/fetch_video_comments")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert state["peak"] <= 2, f"同时在途 {state['peak']} 超过并发上限"
    finally:
        tikhub._reset_limiter()
        get_settings.cache_clear()


def test_mock_mode_does_not_touch_http_or_concurrency(monkeypatch):
    client = TikHubClient(mode="mock")

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise AssertionError("mock 模式不应发 HTTP 请求 / 占并发槽位")

    monkeypatch.setattr(client, "_http", _boom)
    monkeypatch.setattr(tikhub, "_request_slot", _boom)

    data = client.fetch_douyin_author_diagnosis(cookie="c")
    assert data["code"] == 200
