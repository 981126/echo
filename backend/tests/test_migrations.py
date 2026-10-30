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
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM ai_prompts").scalar() == 10
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "r239douyincred"
    engine.dispose()


def test_matching_legacy_database_is_baselines(migration_url):
    run_migrations(migration_url)
    engine = create_engine(migration_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE alembic_version")
    engine.dispose()

    run_migrations(migration_url)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "r239douyincred"
    engine.dispose()


def test_incomplete_legacy_database_is_rejected(migration_url):
    engine = create_engine(migration_url)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE orphan (id integer PRIMARY KEY)")
    engine.dispose()

    with pytest.raises(RuntimeError, match="Cannot baseline"):
        run_migrations(migration_url)
