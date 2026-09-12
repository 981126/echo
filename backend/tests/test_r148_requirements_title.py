"""R-148：需求管理页 UI 溢出的回归测试。

两个来源都要钉住：
1. **解析层**：早期需求文件把「编号-英文 slug」写进了 H1（`# R-094-DOWNLOAD-TIMEOUT-ASR-FAIL-NOTIFY: …`），
   解析时只剥了 `R-094`，把 33 字符无断点 ASCII 留进标题 → 表格被撑破 → 整页横向溢出（实测 108/145 条）。
2. **样式层**：表格单元格必须有 `overflow-wrap: anywhere`（否则任何长串都能再次撑破容器），
   并且宽表要有横向滚动兜底。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.requirement_file import parse_requirement_file

REPO_ROOT = Path(__file__).resolve().parents[2]
REQ_DIR = REPO_ROOT / "requirements"
# slug 残渣的形态：3 段以上全大写 ASCII 用连字符连接（如 DOWNLOAD-TIMEOUT-ASR-FAIL-NOTIFY）。
# 注意不能用「长度 ≥15」当判据 —— `DeepSeek-V4.1-Flash` 这种正常模型名会被误判，
# 普通长串交给样式侧的 `overflow-wrap: anywhere` 换行处理。
_SLUG_TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){2,}\b")
# 极长不可断串（路径/URL 之类）单独兜一层
PATHOLOGICAL_LEN = 30


def test_legacy_slug_title_is_cleaned():
    text = "# R-094-DOWNLOAD-TIMEOUT-ASR-FAIL-NOTIFY: 下载卡住兜底 + 转写原因/通知\n"
    data = parse_requirement_file(text)
    assert data["id"] == "R-094"
    assert data["title"] == "下载卡住兜底 + 转写原因/通知"
    assert not data["title"].startswith("-")


def test_single_segment_slug_is_cleaned():
    data = parse_requirement_file("# R-002-PERSONA: 人设档案=标签+描述，AI建议+手动扩，红线边界\n")
    assert data["id"] == "R-002"
    assert data["title"].startswith("人设档案")


def test_plain_titles_are_untouched():
    """新式 H1 不能被误清洗。"""
    assert parse_requirement_file("# R-110 博主页同步按钮防重复入队\n")["title"] == "博主页同步按钮防重复入队"
    assert parse_requirement_file("# R-141: 邮件是次要通道：配置校验\n")["title"] == "邮件是次要通道：配置校验"
    # 无冒号的连字符标题：保守不剥（宁可留着，也不误伤正常标题）
    assert parse_requirement_file("# R-148-API 接入新模型\n")["title"] == "-API 接入新模型"


def test_slug_only_headline_falls_back_to_slug():
    data = parse_requirement_file("# R-999-SOME-SLUG:\n")
    assert data["id"] == "R-999"
    assert data["title"] == "SOME-SLUG", "剥完为空时回退 slug，而不是空标题"


def test_real_requirement_files_have_no_slug_residue():
    """对真实 requirements/ 全量跑一遍：标题不得残留 slug，也不得含超长不可断 ASCII。

    这条就是「整页溢出」的回归护栏 —— 只要有人再写出 `# R-xxx-SLUG: 标题` 的 H1，
    或者解析规则被改坏，它就会红。
    """
    files = sorted(REQ_DIR.glob("R-*.md"))
    assert files, "requirements/ 下应该有很多需求文件"
    bad_slug: list[str] = []
    long_tokens: list[tuple[str, str]] = []
    for path in files:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        data = parse_requirement_file(first_line + "\n", str(path))
        title = data["title"]
        if title.startswith("-"):
            bad_slug.append(f"{path.name}: {title[:40]}")
        for token in _SLUG_TOKEN_RE.findall(title):
            long_tokens.append((path.name, token[:40]))
        for token in re.findall(r"[A-Za-z0-9_\-\./:]{%d,}" % PATHOLOGICAL_LEN, title):
            long_tokens.append((path.name, token[:40]))
    assert not bad_slug, f"这些标题还残留 slug 前缀：{bad_slug[:5]}"
    assert not long_tokens, f"这些标题含超长不可断串（会撑破表格）：{long_tokens[:5]}"


def test_stylesheet_wraps_long_tokens_in_tables():
    """样式契约①：表格单元格必须允许长串在列内换行。"""
    css = (REPO_ROOT / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "overflow-wrap: anywhere" in css, "缺少长串换行规则 → 长标题会再次撑宽表格"
    assert ".table-wrap" in css and "overflow-x: auto" in css


def test_requirements_table_uses_fixed_layout():
    """样式契约②：需求表必须是**固定列宽**布局。

    实测教训（R-148 第二轮）：只给单元格加 `overflow-wrap` + 外层滚动，**表格本身仍是 1067px**
    （`table-layout:auto` 把剩余空间全给了「状态」下拉那一列：编号 54 / 标题 180 / 状态 805 / 摘要 29），
    在 1440 宽的屏上仍要横向滚动 —— 那只是把溢出圈起来，不是修好。
    固定列宽后表格宽恒等于容器宽（实测 878/775/575/675，内溢出 0）。
    """
    view = (REPO_ROOT / "frontend" / "src" / "views" / "RequirementsView.vue").read_text(encoding="utf-8")
    assert 'class="table table-fixed"' in view, "需求表应使用 .table-fixed"
    assert "table-layout: fixed" in view, "缺少固定列宽布局"
    assert "width: 28%" in view and "width: 132px" in view and "width: 76px" in view, "列宽应由 % / 固定值显式指定"
    assert 'class="table-wrap"' in view, "宽表兜底容器应保留"
    # 之前导致 auto 布局失控的内联 min-width 必须去掉
    assert "min-width: 180px" not in view and "min-width: 130px" not in view, (
        "内联 min-width 会与 table-layout:auto 一起把列撑宽 —— 已改用固定列宽，不要退回"
    )
    # 下拉框要填满它那一列，否则固定列宽下会溢出单元格
    assert 'style="width: 100%"' in view
