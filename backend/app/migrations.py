from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from .db import Base, engine
from . import models  # noqa: F401


def _config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.attributes["database_url"] = database_url
    return config


def _baseline_errors(bind) -> list[str]:
    inspector = inspect(bind)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(Base.metadata.tables)
    errors: list[str] = []
    missing_tables = sorted(expected_tables - actual_tables)
    extra_tables = sorted(actual_tables - expected_tables)
    if missing_tables:
        errors.append(f"missing tables: {', '.join(missing_tables)}")
    if extra_tables:
        errors.append(f"unexpected tables: {', '.join(extra_tables)}")
    for name in sorted(expected_tables & actual_tables):
        expected_columns = set(Base.metadata.tables[name].columns.keys())
        actual_columns = {column["name"] for column in inspector.get_columns(name)}
        missing_columns = sorted(expected_columns - actual_columns)
        extra_columns = sorted(actual_columns - expected_columns)
        if missing_columns:
            errors.append(f"{name} missing columns: {', '.join(missing_columns)}")
        if extra_columns:
            errors.append(f"{name} unexpected columns: {', '.join(extra_columns)}")
    return errors


def run_migrations(database_url: str | None = None) -> None:
    url = database_url or engine.url.render_as_string(hide_password=False)
    bind = create_engine(url, pool_pre_ping=True) if database_url else engine
    try:
        with bind.connect() as connection:
            inspector = inspect(connection)
            has_version_table = inspector.has_table("alembic_version")
            has_application_tables = bool(set(inspector.get_table_names()) - {"alembic_version"})
            if not has_version_table and has_application_tables:
                errors = _baseline_errors(connection)
                if errors:
                    details = "; ".join(errors)
                    raise RuntimeError(f"Cannot baseline a non-matching database: {details}")
                command.stamp(_config(url), "head")
        command.upgrade(_config(url), "head")
    finally:
        if database_url:
            bind.dispose()
