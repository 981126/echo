"""R-243 前端性能优化之后端配套回归。

覆盖：
1) gzip 压缩（JSON 响应带 content-encoding: gzip；小响应不压缩）；
2) 静态资源缓存头（hashed assets immutable / index.html no-cache）；
3) `/api/drafts` 默认排除逻辑删除 + include_deleted/status 可查；
4) `/api/works?slim=1` 不返回 posts 明细，默认行为不变；
5) 封面缩略图生成失败时回退已预热 w400（不回落原图）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.main import app  # noqa: E402
from app.models.draft import Draft  # noqa: E402
from app.models.platform import Creator, CreatorAccount, PlatformPost  # noqa: E402
from app.models.work import Work  # noqa: E402


def _client() -> TestClient:
    return TestClient(app)


def _session_factory():
    eng = fresh_engine()
    ensure_schema(eng)
    return eng, sessionmaker(bind=eng, autoflush=False, autocommit=False)


# ---------- 1) gzip ----------


def test_gzip_compresses_large_json() -> None:
    _eng, S = _session_factory()
    s = S()
    try:
        for i in range(8):
            s.add(Draft(title=f"标题 {i}", script="正文内容 " * 400, status="draft"))
        s.commit()
    finally:
        s.close()
    with _client() as c:
        resp = c.get("/api/drafts?limit=100", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") == "gzip"
        # 解压后仍是合法 JSON 且行数正确（TestClient 自动解压）
        assert len(resp.json()) == 8


def test_small_json_not_compressed() -> None:
    with _client() as c:
        resp = c.get("/api/notifications/unread-count", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") in (None, "identity")


# ---------- 2) 静态缓存头 ----------


def test_hashed_assets_immutable_and_index_no_cache() -> None:
    dist = Path(__file__).resolve().parents[2] / "frontend_v2" / "dist"
    assets = sorted((dist / "assets").glob("*.js")) if (dist / "assets").is_dir() else []
    assert assets, "需要先构建 frontend_v2/dist 才能验证静态缓存头"
    with _client() as c:
        r = c.get(f"/assets/{assets[0].name}")
        assert r.status_code == 200
        assert "immutable" in r.headers.get("cache-control", "")
        assert "max-age=31536000" in r.headers.get("cache-control", "")

        idx = c.get("/index.html")
        assert idx.status_code == 200
        assert idx.headers.get("cache-control") == "no-cache"


# ---------- 3) drafts 默认排除 deleted ----------


def test_drafts_list_excludes_deleted_by_default() -> None:
    _eng, S = _session_factory()
    s = S()
    try:
        s.add_all(
            [
                Draft(title="草稿", script="a", status="draft"),
                Draft(title="完成", script="b", status="done"),
                Draft(title="已删", script="c", status="deleted"),
            ]
        )
        s.commit()
    finally:
        s.close()
    with _client() as c:
        rows = c.get("/api/drafts?limit=100").json()
        assert {r["title"] for r in rows} == {"草稿", "完成"}

        all_rows = c.get("/api/drafts?limit=100&include_deleted=true").json()
        assert {r["title"] for r in all_rows} == {"草稿", "完成", "已删"}

        deleted = c.get("/api/drafts?limit=100&status=deleted").json()
        assert {r["title"] for r in deleted} == {"已删"}


# ---------- 4) works slim ----------


def test_works_slim_omits_posts_details() -> None:
    _eng, S = _session_factory()
    s = S()
    try:
        owner = Creator(kind="owner", name="我", is_current=True)
        s.add(owner)
        s.flush()
        acc = CreatorAccount(
            creator_id=owner.id, platform="douyin", nickname="我的号", platform_user_id="u-slim", enabled=True
        )
        s.add(acc)
        s.flush()
        work = Work(creator_id=owner.id, title="合并作品")
        s.add(work)
        s.flush()
        s.add(
            PlatformPost(
                account_id=acc.id,
                platform="douyin",
                platform_post_id="p-slim-1",
                title="作品一",
                raw="{}",
                work_id=work.id,
            )
        )
        s.commit()
    finally:
        s.close()
    with _client() as c:
        full = c.get("/api/works").json()
        assert full["items"] and full["items"][0]["posts"], "默认响应应包含 posts 明细"

        slim = c.get("/api/works?slim=1").json()
        assert slim["total"] == full["total"]
        assert slim["items"][0]["posts"] == []
        # 其余顶层字段保持
        for key in ("id", "title", "cover", "platforms", "creator_id", "type"):
            assert key in slim["items"][0]


# ---------- 5) 缩略图生成失败 → 回退已预热 w400 ----------


def test_cover_thumb_falls_back_to_w400(monkeypatch, tmp_path) -> None:
    import app.main as main_mod
    from app.core import thumbs

    covers = tmp_path / "covers"
    covers.mkdir()
    src = covers / "封面.jpg"
    src.write_bytes(b"\xff\xd8\xff\xdb fake-jpeg")  # make_thumb 被 mock，内容随意
    fallback = thumbs.thumb_file(covers, src.name, 400)
    fallback.parent.mkdir(parents=True, exist_ok=True)
    fallback.write_bytes(b"thumb-400")
    target = thumbs.thumb_file(covers, src.name, 160)
    assert not target.is_file()

    monkeypatch.setattr(main_mod._settings, "covers_dir", covers)
    monkeypatch.setattr(thumbs, "make_thumb", lambda *args, **kwargs: False)

    resp = main_mod.cover_file(src.name, 160)
    assert isinstance(resp, FileResponse)
    assert Path(resp.path) == fallback, "生成失败应回退预热的 w400 缩略图，而不是原图"
    assert resp.headers["cache-control"].startswith("public")
