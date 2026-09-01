from __future__ import annotations

"""纯逻辑（无第三方依赖）：需求归档文件解析与编号。"""
import re

STATUSES = ["已登记", "澄清中", "已确认", "实施中", "已完成", "已搁置", "已拒绝"]
ID_RE = re.compile(r"^R-(\d{3})")


def parse_requirement_file(text: str, path: str = "") -> dict:
    """解析 R-xxx.md 文本 → 字段。"""
    title = ""
    status = "已登记"
    summary = ""
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    m = re.match(r"^#\s+(R-\d{3})[::\s]*(.*)$", first_line)
    rid = m.group(1) if m else ""
    if m and m.group(2):
        title = m.group(2).strip()
    for line in lines:
        sm = re.match(r"^-\s*\*\*状态\*\*[:：]\s*(.+)$", line.strip())
        if sm:
            status = sm.group(1).strip()
        um = re.match(r"^-\s*\*\*原文摘要\*\*[:：]\s*(.+)$", line.strip())
        if um:
            summary = um.group(1).strip()
    return {"id": rid, "title": title, "status": status, "summary": summary, "path": path}


def next_requirement_id(existing_ids: list[str]) -> str:
    """取下一个需求编号（R-001 起递增）。"""
    nums = []
    for rid in existing_ids:
        m = ID_RE.match(rid or "")
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return f"R-{nxt:03d}"
