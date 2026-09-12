"""需求归档服务：**只读** requirements/ 文件夹（事实源）。

R-149 起「需求管理」网页下线，登记/改状态的写接口一并移除（新需求由 AI 按 AGENTS.md 流程
直接写入 `requirements/R-xxx.md`）。这里只保留 AI 对话「查需求归档」工具需要的能力。
"""

from __future__ import annotations

from pathlib import Path

from ..core.requirement_file import parse_requirement_file

REQ_DIR = Path(__file__).resolve().parents[3] / "requirements"


def _iter_files() -> list[Path]:
    if not REQ_DIR.exists():
        return []
    return sorted(p for p in REQ_DIR.glob("R-*.md") if p.is_file())


def list_requirements() -> list[dict]:
    return [parse_requirement_file(p.read_text(encoding="utf-8"), str(p)) for p in _iter_files()]
