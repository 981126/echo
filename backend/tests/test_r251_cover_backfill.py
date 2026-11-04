"""R-251：补齐云端作品缺失封面（历史同步中断/下载失败留下的空 cover_path / 占位 SVG）。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ensure_schema, fresh_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models.platform import Creator, CreatorAccount, PlatformPost  # noqa: E402
from app.services import platform_assets, platform_sync  # noqa: E402


def _session_factory():
    eng = fresh_engine()
    ensure_schema(eng)
    return eng, sessionmaker(bind=eng, autoflush=False, autocommit=False)


def _seed(s) -> tuple[Creator, CreatorAccount]:
    owner = Creator(kind="owner", name="我", is_current=True)
    s.add(owner)
    s.flush()
    account = CreatorAccount(creator_id=owner.id, platform="douyin", nickname="我的抖音", enabled=True)
    s.add(account)
    s.commit()
    return owner, account


def _post(s, account: CreatorAccount, pid: str, cover_path: str, title: str = "测试作品") -> PlatformPost:
    post = PlatformPost(
        account_id=account.id,
        platform="douyin",
        platform_post_id=pid,
        title=title,
        cover_path=cover_path,
        cover_url="https://cdn.example.com/cover.heic",
        raw="{}",
    )
    s.add(post)
    s.commit()
    return post


def test_backfill_missing_cover_path(tmp_path, monkeypatch):
    _eng, S = _session_factory()
    s = S()
    try:
        _owner, account = _seed(s)
        empty = _post(s, account, "p-empty", "")
        placeholder = _post(s, account, "p-svg", "抖音-测试作品-封面.svg")
        ok = _post(s, account, "p-ok", "抖音-已存在-封面.jpg")

        calls: list[tuple[str, str]] = []

        def fake_cover(platform, post_id, title, cover_url, *, reuse_svg=""):
            calls.append((post_id, reuse_svg))
            return f"抖音-{post_id}-封面.jpg"

        monkeypatch.setattr(platform_sync, "_cover_path_for", fake_cover)
        monkeypatch.setattr(
            platform_sync, "get_settings", lambda: SimpleNamespace(covers_dir=tmp_path)
        )

        fixed = platform_sync._backfill_account_covers(s, account)
        s.refresh(empty)
        s.refresh(placeholder)
        s.refresh(ok)
        assert fixed == 2  # 只修空值 + 占位 SVG，已存在真实封面的行不命中
        assert empty.cover_path == "抖音-p-empty-封面.jpg"
        assert placeholder.cover_path == "抖音-p-svg-封面.jpg"
        assert ok.cover_path == "抖音-已存在-封面.jpg"
        assert all(item[0] != "p-ok" for item in calls)
        # 占位 SVG 重试会带上 reuse_svg，失败时可复用旧占位
        assert ("p-svg", "抖音-测试作品-封面.svg") in calls
    finally:
        s.close()


def test_backfill_no_missing_rows_is_noop(tmp_path, monkeypatch):
    _eng, S = _session_factory()
    s = S()
    try:
        _owner, account = _seed(s)
        _post(s, account, "p-ok", "抖音-已存在-封面.jpg")
        monkeypatch.setattr(
            platform_sync, "get_settings", lambda: SimpleNamespace(covers_dir=tmp_path)
        )
        assert platform_sync._backfill_account_covers(s, account) == 0
    finally:
        s.close()


def test_cover_path_reuses_svg_when_download_fails(tmp_path, monkeypatch):
    svg = tmp_path / "占位-封面.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")

    class FakeClient:
        def get(self, *args, **kwargs):
            raise RuntimeError("cdn down")

    monkeypatch.setattr(platform_assets, "get_settings", lambda: SimpleNamespace(covers_dir=tmp_path))
    monkeypatch.setattr(platform_assets, "get_client", lambda *args, **kwargs: FakeClient())

    name = platform_assets._cover_path_for(
        "douyin", "p1", "测试作品", "https://cdn.example.com/a.heic", reuse_svg="占位-封面.svg"
    )
    assert name == "占位-封面.svg"
    # 不能因重试而新建 -2/-3 占位
    assert not list(tmp_path.glob("测试作品-封面*.svg"))
