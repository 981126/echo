#!/usr/bin/env python3
"""文档一致性检查（R-136）：DATABASE.md 表数量与实际代码是否一致；API.md 存在时校验路由。

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

    # ---------- 路由（docs/API.md 已随文档精简删除，仅当文件存在时校验） ----------
    spec = app.main.app.openapi()
    paths = spec["paths"]
    operations = sum(len(v) for v in paths.values())
    api_md_path = ROOT / "docs" / "API.md"
    if api_md_path.exists():
        api_md = api_md_path.read_text(encoding="utf-8")
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

    # ---------- 需求文档 ↔ 开发设计文档成对检查（R-237 起强制） ----------
    # 历史需求（R-001~R-236）只登记了需求、没有开发设计，不追溯；从 R-237 起两份文档缺一不可。
    req_dir = ROOT / "requirements"
    design_dir = ROOT / "development-design"
    since = 237
    requirement_files = {
        path.name: int(m.group(1))
        for path in req_dir.glob("R-*.md")
        if (m := re.match(r"R-(\d+)-", path.name))
    }
    for name, number in sorted(requirement_files.items()):
        if number >= since and not (design_dir / name).exists():
            problems.append(f"需求缺少同名开发设计：requirements/{name} → development-design/{name}")
    for path in design_dir.glob("R-*.md"):
        if path.name not in requirement_files:
            problems.append(f"开发设计缺少对应需求文档：development-design/{path.name}")

    if problems:
        print("==> [docs] 文档与代码不一致：")
        return _fail(problems)
    api_note = f"{operations} 个路由" if api_md_path.exists() else "API.md 已删除（跳过路由校验）"
    print(f"==> [docs] 一致：{len(tables)} 张表 / {api_note} / 需求与设计文档成对")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
