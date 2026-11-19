"""R-263 迁移前 PostgreSQL 逻辑备份与表计数。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    settings = get_settings()
    url = make_url(settings.database_url)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dump = args.output_dir / f"r263-before-{stamp}.dump"
    report = args.output_dir / f"r263-before-{stamp}.json"
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        counts = {
            table: connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            for table in inspect(connection).get_table_names()
            if table != "alembic_version"
        }
    command = [
        "pg_dump",
        "--format=custom",
        "--file",
        str(dump),
        "--host",
        url.host or "localhost",
        "--port",
        str(url.port or 5432),
        "--username",
        url.username or "",
        url.database or "",
    ]
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = url.password
    subprocess.run(command, check=True, env=env)
    if not dump.is_file() or dump.stat().st_size == 0:
        raise RuntimeError("数据库备份失败：dump 文件为空")
    report.write_text(
        json.dumps(
            {"database": url.database, "dump": str(dump), "bytes": dump.stat().st_size, "tables": counts},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(report)


if __name__ == "__main__":
    main()
