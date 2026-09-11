#!/usr/bin/env python3
"""文档一致性检查（R-136）：DATABASE.md 表数量、API.md 路由数量与实际代码是否一致。

用法（仓库根目录）：`PYTHONPATH=backend python3 scripts/check_doc_consistency.py`
退出码：0=一致；1=不一致（会打印差异，供 verify.sh 判定门禁）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _fail(lines: list[str]) -> int:
    for line in lines:
        print(f"  ✘ {line}")
    return 1


def main() -> int:
    from app.db import Base
    import app.main  # noqa: F401  触发模型注册与路由注册
    import app.models  # noqa: F401

    problems: list[str] = []

    # ---------- 表数量 ----------
    tables = sorted(Base.metadata.tables.keys())
    database_md = (ROOT / "docs" / "DATABASE.md").read_text(encoding="utf-8")
    m = re.search(r"表总览（(\d+)\s*张）", database_md)
    if not m:
        problems.append("DATABASE.md 找不到「表总览（N 张）」")
    elif int(m.group(1)) != len(tables):
        problems.append(f"DATABASE.md 写 {m.group(1)} 张表，代码实际 {len(tables)} 张")
    for table in tables:
        if f"## `{table}`" not in database_md:
            problems.append(f"DATABASE.md 缺少表章节：{table}")
    for section in re.findall(r"^## `([a-z_]+)`$", database_md, flags=re.M):
        if section not in tables and section not in {"表总览"}:
            problems.append(f"DATABASE.md 有已不存在的表章节：{section}")

    # ---------- 路由 ----------
    spec = app.main.app.openapi()
    paths = spec["paths"]
    operations = sum(len(v) for v in paths.values())
    api_md = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    m2 = re.search(r"共\s*(\d+)\s*个路由", api_md)
    if not m2:
        problems.append("API.md 找不到「共 N 个路由」")
    elif int(m2.group(1)) != operations:
        problems.append(f"API.md 写 {m2.group(1)} 个路由，OpenAPI 实际 {operations} 个 operation")
    documented = set()
    for method, path in re.findall(r"^### (GET|POST|PUT|PATCH|DELETE) (\S+)$", api_md, flags=re.M):
        documented.add((method, path))
    for path, item in paths.items():
        for method in item:
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if (method.upper(), path) not in documented:
                problems.append(f"API.md 缺少路由：{method.upper()} {path}")

    if problems:
        print("==> [docs] 文档与代码不一致：")
        return _fail(problems)
    print(f"==> [docs] 一致：{len(tables)} 张表 / {operations} 个路由")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
