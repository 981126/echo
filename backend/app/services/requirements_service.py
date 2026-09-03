"""需求归档服务：读写 requirements/ 文件夹（事实源）。"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from ..core.requirement_file import STATUSES, next_requirement_id, parse_requirement_file

REQ_DIR = Path(__file__).resolve().parents[3] / "requirements"


class RequirementError(RuntimeError):
    pass


def _iter_files() -> list[Path]:
    if not REQ_DIR.exists():
        return []
    return sorted(p for p in REQ_DIR.glob("R-*.md") if p.is_file())


def list_requirements() -> list[dict]:
    return [parse_requirement_file(p.read_text(encoding="utf-8"), str(p)) for p in _iter_files()]


def get_requirement(rid: str) -> dict:
    rid = rid.upper()
    for p in _iter_files():
        if p.name.upper().startswith(rid):
            text = p.read_text(encoding="utf-8")
            data = parse_requirement_file(text, str(p))
            data["content"] = text
            return data
    raise RequirementError(f"需求不存在: {rid}")


def create_requirement(title: str, summary: str) -> dict:
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    existing = [p.name for p in _iter_files()]
    rid = next_requirement_id(existing)
    today = datetime.date.today().isoformat()
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-")[:20] or "req"
    filename = f"{rid}-{slug}.md"
    content = (
        f"# {rid}: {title}\n\n"
        f"- **日期**: {today}\n"
        f"- **提出渠道**: Web 需求管理\n"
        f"- **原文摘要**: {summary or '（待补充）'}\n"
        f"- **状态**: 已登记\n"
        f"- **排期**: 待定\n"
        f"- **关联**: 待定\n"
    )
    path = REQ_DIR / filename
    path.write_text(content, encoding="utf-8")
    data = parse_requirement_file(content, str(path))
    data["content"] = content
    return data


def update_status(rid: str, status: str) -> dict:
    if status not in STATUSES:
        raise RequirementError(f"非法状态: {status}（可选 {'/'.join(STATUSES)}）")
    data = get_requirement(rid)
    path = Path(data["path"])
    text = data["content"]
    new_text = re.sub(
        r"^-\s*\*\*状态\*\*[:：].*$",
        f"- **状态**: {status}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(new_text, encoding="utf-8")
    return parse_requirement_file(new_text, str(path))
