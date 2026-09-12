"""R-142 校准护栏：推理预算必须覆盖实测需求，改小就红。

**为什么需要这个文件**：作者反馈过「模型1 调用失败，已降级模型2（脚本生成）…为什么总是这样」。
根因是预算被拍成了 4000，正好落在「同一步骤思考量波动区间」内 → 约一半概率被截断成空正文 → 误判降级。
把值改成实测最坏值之后，如果再有人手滑调小（或新增调用点时随手写个 3000），
不应该等到线上出现降级通知才发现 —— 所以把「实测基准」固化成断言。

**实测方法与基准**（2026-09-12，同一份评审提示词 2974 字 + 真实脚本 968 字，只改 max_tokens）：

| max_tokens | finish_reason | 思考 | 正文 | reasoning_tokens |
|---|---|---|---|---|
| 4000 | length | 5961 字 | 0 | 4001 |
| 8000 | stop | 9869 字 | 833 字 | 6493 |
| 12000 | stop | 9649 字 | 1034 字 | 6296 |
| 16000 | stop | 12215 字 | 1031 字 | 8023 |
| 4000（复测） | stop | 3945 字 | 1286 字 | 2418 |

复现方式：`tests` 同目录的思路 —— 不传 stream、逐个 max_tokens 打真实接口，
记录 `finish_reason / reasoning_content 长度 / usage.completion_tokens_details.reasoning_tokens`。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import debate as debate_mod
from app.services import llm_router, model_settings

# 实测基准：同一步骤的思考量波动区间上界（reasoning_tokens）
MEASURED_WORST_REASONING_TOKENS = 8023
# 实测最坏值之外还要留的余量倍数（正文 + 波动）
HEADROOM = 1.2


def test_vendor_floors_cover_measured_worst_case():
    """厂家下限必须覆盖实测最坏思考量，否则任何调用方都可能被截断。"""
    for vendor, meta in model_settings.VENDORS.items():
        assert meta["min_max_tokens"] >= MEASURED_WORST_REASONING_TOKENS, (
            f"{vendor} 的 min_max_tokens={meta['min_max_tokens']} 低于实测最坏思考量 "
            f"{MEASURED_WORST_REASONING_TOKENS}（见本文件头部的量测表）"
        )


def test_debate_step_budgets_cover_measured_worst_case():
    """双模型讨论各步预算必须覆盖实测最坏思考量（这是「评审总是降级」的直接原因）。"""
    required = int(MEASURED_WORST_REASONING_TOKENS * HEADROOM)
    for name, value in (
        ("BUDGET_INITIAL", debate_mod.BUDGET_INITIAL),
        ("BUDGET_CRITIQUE", debate_mod.BUDGET_CRITIQUE),
        ("BUDGET_REVISE", debate_mod.BUDGET_REVISE),
    ):
        assert value >= required, (
            f"{name}={value} 低于「实测最坏 {MEASURED_WORST_REASONING_TOKENS} tokens × {HEADROOM} 余量」"
            f"＝{required}；改小之前请先重跑本文件头部的量测"
        )


def test_escalation_ceiling_leaves_room_for_retry():
    """翻倍重试要留出空间：封顶至少是最大厂家下限的 2 倍（否则重试等于原地打转）。"""
    biggest_floor = max(meta["min_max_tokens"] for meta in model_settings.VENDORS.values())
    assert llm_router.MAX_TOKENS_CEILING >= biggest_floor * 2
