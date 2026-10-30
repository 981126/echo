"""R-240：请求耗时中间件回归（只验证观测能力，不改变业务响应）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_has_response_time_header() -> None:
    """/health 也要带 X-Response-Time（毫秒浮点、非负）。"""
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    value = resp.headers.get("x-response-time")
    assert value is not None
    assert float(value) >= 0.0


def test_error_response_keeps_response_time_header() -> None:
    """校验失败的请求同样能被观测到（中间件不能吞异常/改状态码）。"""
    resp = TestClient(app).get("/api/drafts/not-an-int")
    assert resp.status_code == 422
    assert "x-response-time" in resp.headers
