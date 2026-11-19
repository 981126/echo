from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.core.analytics_views import allowed_views
from app.db import Base
from app.migrations import run_migrations


@pytest.fixture()
def migration_url():
    base = make_url(get_settings().database_url)
    name = f"echo_test_migration_{uuid.uuid4().hex}"
    admin = psycopg.connect(
        host=base.host,
        port=base.port,
        dbname=base.database,
        user=base.username,
        password=base.password,
        autocommit=True,
    )
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        admin.close()


def test_empty_database_upgrade_and_repeat(migration_url):
    run_migrations(migration_url)
    run_migrations(migration_url)

    engine = create_engine(migration_url)
    inspector = inspect(engine)
    assert set(Base.metadata.tables) <= set(inspector.get_table_names())
    assert allowed_views() <= set(inspector.get_view_names())
    assert "verdict" in {column["name"] for column in inspector.get_columns("video_review_findings")}
    with engine.connect() as connection:
        # R-263：38 条系统提示词/探针 + 3 条 v2；47 条注册项（契约不版本化）
        assert connection.exec_driver_sql("SELECT count(*) FROM ai_prompts").scalar() == 41
        assert connection.exec_driver_sql("SELECT count(*) FROM ai_prompt_defs").scalar() == 47
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "r266openings"
    engine.dispose()


def test_matching_legacy_database_is_baselines(migration_url):
    run_migrations(migration_url)
    engine = create_engine(migration_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE alembic_version")
    engine.dispose()

    run_migrations(migration_url)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "r266openings"
    engine.dispose()


def test_incomplete_legacy_database_is_rejected(migration_url):
    engine = create_engine(migration_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE orphan (id integer PRIMARY KEY)")
    engine.dispose()

    with pytest.raises(RuntimeError, match="Cannot baseline"):
        run_migrations(migration_url)


def test_legacy_discussions_migrate_only_clear_normal_generation(migration_url):
    from alembic import command
    from sqlalchemy import text

    from app.migrations import _config

    run_migrations(migration_url)
    engine = create_engine(migration_url)
    from sqlalchemy.orm import sessionmaker

    from app.models.discussion import DraftDiscussion
    from app.models.draft import Draft
    from app.models.platform import Creator

    session = sessionmaker(bind=engine)()
    with session.begin():
        owner = Creator(kind="owner", name="我", is_current=True)
        session.add(owner)
        session.flush()
        normal = Draft(creator_id=owner.id, title="旧普通生成", source="ai", original_script="", script="最终稿")
        benchmark = Draft(
            creator_id=owner.id,
            title="洗稿",
            source="ai",
            original_script="原文",
            script="洗稿后",
            source_ref='{"kind":"benchmark"}',
        )
        manual = Draft(creator_id=owner.id, title="历史原文讨论", source="manual", original_script="原文", script="讨论后")
        session.add_all([normal, benchmark, manual])
        session.flush()
        for draft in (normal, benchmark, manual):
            session.add_all(
                [
                    DraftDiscussion(draft_id=draft.id, actor="system", kind="run", content="留痕"),
                    DraftDiscussion(draft_id=draft.id, actor="system", kind="draft", content="留痕"),
                ]
            )
        session.flush()
        normal_id, benchmark_id, manual_id = normal.id, benchmark.id, manual.id
    session.close()
    command.downgrade(_config(migration_url), "r255promptdefs")
    run_migrations(migration_url)

    with engine.connect() as connection:
        legacy = connection.execute(
            text("SELECT draft_id, attempts_json, quality_passed FROM generation_runs WHERE status = 'legacy'")
        ).mappings().one()
        assert legacy["draft_id"] == normal_id
        assert legacy["quality_passed"] is False
        import json

        assert len(json.loads(legacy["attempts_json"])["legacy_discussions"]) == 2
        remaining = {
            row[0]
            for row in connection.execute(text("SELECT DISTINCT draft_id FROM draft_discussions")).all()
        }
        assert remaining == {benchmark_id, manual_id}
    engine.dispose()
