
"""纯逻辑（无第三方依赖）：需求归档文件解析与编号。"""

from __future__ import annotations

import re



# 老式 H1：`# R-094-DOWNLOAD-TIMEOUT-ASR-FAIL-NOTIFY: 中文标题`
# （早期需求文件把「编号-英文 slug」当标题写，108/108 条 slug 后面都带冒号）
_SLUG_TITLE_RE = re.compile(r"^#\s+(R-\d{3})-([A-Za-z0-9][A-Za-z0-9\-]*)\s*[:：]\s*(.*)$")
# 新式 H1：`# R-110 博主页同步按钮…` / `# R-141: 邮件是次要通道…`
_PLAIN_TITLE_RE = re.compile(r"^#\s+(R-\d{3})\s*[:：]?\s*(.*)$")


def _parse_headline(first_line: str) -> tuple[str, str]:
    """从 H1 取 (编号, 人类可读标题)。

    R-148：老式标题里的英文 slug 必须剥掉 —— 否则会以「33 字符无断点 ASCII」的形式进入
    需求管理页表格，把整页撑宽（实测：108/145 条被污染）。
    规则保守：只有「ID 后面紧跟 `-`，且 slug 以冒号结尾」才算 slug，
    避免误伤 `# R-148-API 接入…` 这种正常标题；剥完为空则回退原值。
    """
    m = _SLUG_TITLE_RE.match(first_line)
    if m:
        rid, title = m.group(1), m.group(3).strip()
        if title:
            return rid, title
        # 剥完没内容 → 退回 slug 本身（总比空白好）
        return rid, m.group(2).strip()
    m = _PLAIN_TITLE_RE.match(first_line)
    if m:
        return m.group(1), m.group(2).strip()
    return "", ""


def parse_requirement_file(text: str, path: str = "") -> dict:
    """解析 R-xxx.md 文本 → 字段。"""
    title = ""
    status = "已登记"
    summary = ""
    lines = text.splitlines()
    first_line = lines[0] if lines else ""
    rid, title = _parse_headline(first_line)
    for line in lines:
        sm = re.match(r"^-\s*\*\*状态\*\*[:：]\s*(.+)$", line.strip())
        if sm:
            status = sm.group(1).strip()
        um = re.match(r"^-\s*\*\*原文摘要\*\*[:：]\s*(.+)$", line.strip())
        if um:
            summary = um.group(1).strip()
    return {"id": rid, "title": title, "status": status, "summary": summary, "path": path}
