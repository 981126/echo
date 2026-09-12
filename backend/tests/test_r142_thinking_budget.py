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

from app.services import llm_router, model_settings

# 实测基准：同一步骤的思考量波动区间上界（reasoning_tokens）
MEASURED_WORST_REASONING_TOKENS = 8023
# 实测最坏值之外还要留的余量倍数（正文 + 波动）
HEADROOM = 1.2


def test_vendor_floor_is_a_sane_safety_net():
    """厂家下限是安全网（兜住「有人随手写 300」），不是按任务标定的替代品。

    R-143 起「每个功能要多少」由 `budget_settings.SLOTS` 按任务标定且可配置；
    下限只需要「给推理模型留出基本思考空间」，过高的下限会把所有小功能的配置压平。
    """
    for vendor, meta in model_settings.VENDORS.items():
        assert 2000 <= meta["min_max_tokens"] <= 12000, (
            f"{vendor} 的 min_max_tokens={meta['min_max_tokens']} 不合理："
            "低于 2000 会饿死推理模型，高于 12000 会把各功能按任务标定的预算压平"
        )


# 长输出 / 长思考类功能：默认预算必须覆盖实测最坏值（这些才是「被截断 → 降级」的高危项）
LONG_OUTPUT_SLOTS = ("debate_initial", "debate_critique", "debate_revise", "rewrite", "correct")


def test_long_output_budgets_cover_measured_worst_case():
    """这些功能的默认预算必须 ≥ 实测最坏思考量 × 余量（R-142 的直接教训）。"""
    from app.services import budget_settings

    required = int(MEASURED_WORST_REASONING_TOKENS * HEADROOM)
    for key in LONG_OUTPUT_SLOTS:
        value = int(budget_settings.SLOTS[key]["default"])
        assert value >= required, (
            f"{key} 默认预算={value} 低于「实测最坏 {MEASURED_WORST_REASONING_TOKENS} tokens × {HEADROOM}」"
            f"＝{required}；改小之前请先重跑本文件头部的量测"
        )


def test_escalation_ceiling_leaves_room_for_retry():
    """翻倍重试要留出空间：封顶至少是最大厂家下限的 2 倍（否则重试等于原地打转）。"""
    biggest_floor = max(meta["min_max_tokens"] for meta in model_settings.VENDORS.values())
    assert llm_router.MAX_TOKENS_CEILING >= biggest_floor * 2
