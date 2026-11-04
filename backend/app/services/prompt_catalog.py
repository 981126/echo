"""AI 提示词注册表（R-255）：全部系统提示词 + 程序固定契约的唯一定义源。

设计要点：
- 一行一条 `PromptSpec`，登记 key / 中文名 / 模块 / 中文用途说明 / 类型 / 是否可编辑 /
  是否可优化 / 模型路由 feature / 触发入口 / 代码默认正文位置 / 代码位置 / 展示顺序。
- 本模块**不得在模块级 import 业务 service**（否则与 prompt_service 形成循环导入）：
  代码默认正文通过 `default_content()` 惰性 import 解析，与 R-021 的既有做法一致。
- `ai_prompt_defs` 表由 Alembic 迁移与本模块共同种子；`ai_prompts` 继续存版本正文。
- 详细设计见 `development-design/R-255-prompt-registry.md`。
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Literal

Category = Literal["system", "probe", "contract"]

# 模块顺序 = 页面分组顺序；module_label 是作者要的「中文模块名」
MODULES: list[tuple[str, str]] = [
    ("generation", "脚本生成"),
    ("rewrite", "对标洗稿"),
    ("benchmark", "对标分析"),
    ("persona", "人设引擎"),
    ("material", "素材导入"),
    ("learning", "改稿学习"),
    ("review", "视频复盘"),
    ("chat", "AI 对话"),
    ("ideas", "选题灵感"),
    ("opportunity", "内容机会"),
    ("evidence", "素材检索"),
    ("draft_meta", "草稿元信息"),
    ("prompt_ops", "提示词优化"),
    ("selfcheck", "系统自检"),
]
MODULE_LABELS: dict[str, str] = dict(MODULES)
_MODULE_INDEX: dict[str, int] = {name: i for i, (name, _label) in enumerate(MODULES)}


@dataclass(frozen=True)
class PromptSpec:
    """一条提示词的静态登记信息（不含版本正文，正文在 ai_prompts）。"""

    key: str
    title: str
    module: str
    module_label: str
    purpose: str
    entry: str
    code_ref: str
    category: Category = "system"
    editable: bool = True
    optimizable: bool = False
    llm_feature: str = ""
    sort_order: int = 0
    # (模块路径, 常量名)；contract 类为 None，正文从 prompt_contract.CONTRACTS 取
    default_ref: tuple[str, str] | None = None


def _s(
    seq: int,
    key: str,
    title: str,
    module: str,
    purpose: str,
    entry: str,
    code_ref: str,
    default_ref: tuple[str, str] | None,
    *,
    category: Category = "system",
    editable: bool = True,
    optimizable: bool = False,
    llm_feature: str = "",
) -> PromptSpec:
    return PromptSpec(
        key=key,
        title=title,
        module=module,
        module_label=MODULE_LABELS[module],
        purpose=purpose,
        entry=entry,
        code_ref=code_ref,
        category=category,
        editable=editable,
        optimizable=optimizable,
        llm_feature=llm_feature,
        sort_order=_MODULE_INDEX[module] * 100 + seq,
        default_ref=default_ref,
    )


PROMPT_SPECS: list[PromptSpec] = [
    # ---------- 模块 1｜脚本生成 ----------
    _s(
        1,
        "generation",
        "生成脚本",
        "generation",
        "生成脚本主提示词：告诉生成方 AI 以作者代笔身份写作，并约束论点/支撑/素材可用性/口语化等硬要求；"
        "输入选题+作者上下文，输出标题、封面字、口播脚本、论点、来源与平台外壳 JSON。"
        "用于脚本工作台 AI 生成/回炉、每日自动生成、视频复盘「采用」、主页灵感与随手记生成等全部生成入口。",
        "脚本工作台 AI 生成/回炉、每日自动生成、视频复盘「采用」、主页灵感/随手记生成、金样本自测",
        "app/services/generation.py:31 · GENERATION_SYSTEM",
        ("app.services.generation", "GENERATION_SYSTEM"),
        optimizable=True,
        llm_feature="generation",
    ),
    _s(
        2,
        "debate_critic_generate",
        "讨论-评审（生成链）",
        "generation",
        "生成链双模型讨论的评审提示词：对照作者人设、红线与语言习惯，检查当前脚本哪里不像作者、哪里有 AI 感、"
        "论点是否够硬、是否空洞，输出纯文本修改意见；每轮讨论调用一次。",
        "双模型讨论 run_debate（生成/基于原文讨论）每轮评审",
        "app/services/debate.py · CRITIC_SYSTEM_GENERATE",
        ("app.services.debate", "CRITIC_SYSTEM_GENERATE"),
        llm_feature="generation",
    ),
    _s(
        3,
        "debate_revise_generate",
        "讨论-修订（生成链）",
        "generation",
        "生成链双模型讨论的修订提示词：按评审意见用作者口吻重写整篇口播稿（只输出脚本正文），"
        "红线自检不通过时也用它做整篇重写。",
        "双模型讨论 run_debate 每轮修订 + 红线自检重写",
        "app/services/debate.py · REVISE_SYSTEM_GENERATE",
        ("app.services.debate", "REVISE_SYSTEM_GENERATE"),
        llm_feature="generation",
    ),
    _s(
        4,
        "generation.contract",
        "生成脚本契约",
        "generation",
        "生成脚本的输出 JSON 契约：固定 title/cover_text/script/shells 字段与结构，程序按此解析生成结果（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['generation']",
        None,
        category="contract",
        editable=False,
    ),
    # ---------- 模块 2｜对标洗稿 ----------
    _s(
        1,
        "rewrite_from_source",
        "基于原文改写",
        "rewrite",
        "基于原文改写的系统提示词：把给定素材当作可用内容，用作者人设口吻写成可直接录的口播稿，"
        "输出标题/封面字/脚本/标签 JSON；用于草稿「基于原文讨论」首轮。",
        "草稿「基于原文讨论」首轮（POST /api/drafts/{id}/discuss）",
        "app/services/debate.py:314 · SOURCE_REWRITE_SYSTEM",
        ("app.services.debate", "SOURCE_REWRITE_SYSTEM"),
        llm_feature="generation",
    ),
    _s(
        2,
        "rewrite_critic",
        "洗稿讨论-评审",
        "rewrite",
        "洗稿链双模型讨论的评审提示词：对照作者完整上下文与参考原文，指出不像作者、AI 腔、逐字照抄和内容质量问题，"
        "输出纯文本修改意见。",
        "对标洗稿双模型讨论（POST /api/benchmark/rewrite）",
        "app/services/debate.py · CRITIC_SYSTEM_REWRITE",
        ("app.services.debate", "CRITIC_SYSTEM_REWRITE"),
        llm_feature="generation",
    ),
    _s(
        3,
        "rewrite_revise",
        "洗稿讨论-修订",
        "rewrite",
        "洗稿链双模型讨论的修订提示词：按评审意见用作者口吻重写整篇口播稿，只输出脚本正文。",
        "对标洗稿双模型讨论",
        "app/services/debate.py · REVISE_SYSTEM_REWRITE",
        ("app.services.debate", "REVISE_SYSTEM_REWRITE"),
        llm_feature="generation",
    ),
    _s(
        4,
        "rewrite_from_benchmark",
        "对标洗稿初稿",
        "rewrite",
        "对标洗稿初稿系统提示词：把对标博主素材写成作者本人的口播稿，要求 2~4 条明确论点及具体支撑、"
        "不复用原文结构，输出标题/封面字/脚本/标签/论点/来源 JSON。",
        "对标洗稿首轮（benchmark_rewrite 后台任务）",
        "app/services/benchmark.py:650 · REWRITE_SYSTEM",
        ("app.services.benchmark", "REWRITE_SYSTEM"),
        llm_feature="generation",
    ),
    # ---------- 模块 3｜对标分析 ----------
    _s(
        1,
        "benchmark_ad_judge",
        "对标广告判定（单条）",
        "benchmark",
        "对标广告判定（单条）提示词：判断一条对标视频口播是否广告/商单/带货/引流，输出 is_ad 与简短理由；"
        "用于对标候选广告过滤。",
        "对标候选广告过滤（单条判定）",
        "app/services/benchmark.py · _AD_JUDGE_SYSTEM",
        ("app.services.benchmark", "_AD_JUDGE_SYSTEM"),
        llm_feature="benchmark",
    ),
    _s(
        2,
        "benchmark_ad_judge_batch",
        "对标广告判定（批量）",
        "benchmark",
        "对标广告判定（批量）提示词：一次判断多条候选是否广告/商单/引流，输出 results 数组"
        "（id/is_ad/reason）；用于对标候选批量过滤。",
        "对标候选广告过滤（批量判定）",
        "app/services/benchmark.py · _AD_BATCH_SYSTEM",
        ("app.services.benchmark", "_AD_BATCH_SYSTEM"),
        llm_feature="benchmark",
    ),
    _s(
        3,
        "benchmark_analyze",
        "对标「我能不能讲」",
        "benchmark",
        "对标分析「我能不能讲」提示词：结合作者人设与红线，判断一条对标文案是否契合作者、能不能讲、"
        "是否与已有内容重复，输出 can/reason/suggestion。",
        "对标分析（POST /api/benchmark/analyze）",
        "app/services/benchmark.py · ANALYZE_SYSTEM",
        ("app.services.benchmark", "ANALYZE_SYSTEM"),
        llm_feature="benchmark",
    ),
    # ---------- 模块 4｜人设引擎 ----------
    _s(
        1,
        "persona_init",
        "人设逐篇提取",
        "persona",
        "人设逐篇提取提示词：读一篇作者口播转写稿，提炼真实存在的人设信号（标签/描述/维度/原文证据）与红线；"
        "单篇一次调用，宁少勿滥。",
        "人设初始化/重建/重新校验、导入视频后自动（persona_* 后台任务）",
        "app/services/persona.py:24 · PERSONA_INIT_SYSTEM",
        ("app.services.persona", "PERSONA_INIT_SYSTEM"),
        optimizable=True,
        llm_feature="persona_init",
    ),
    _s(
        2,
        "persona_merge",
        "人设归纳合并",
        "persona",
        "人设归纳合并提示词：把同一作者多篇提炼结果总结去重，按四层（core_dna/stance/mode/forbidden）"
        "归成完整人设档案。",
        "人设合并（init/rebuild/recheck 任务）",
        "app/services/persona.py:45 · PERSONA_MERGE_SYSTEM",
        ("app.services.persona", "PERSONA_MERGE_SYSTEM"),
        optimizable=True,
        llm_feature="persona_merge",
    ),
    _s(
        3,
        "persona_updates",
        "人设增量合并",
        "persona",
        "人设增量合并提示词：把当前四层档案与一篇新文案提炼结果合并，冲突时以新文案为准、不凭空删条目。",
        "人设增量合并（recheck、导入视频后自动）",
        "app/services/persona.py:66 · PERSONA_UPDATES_SYSTEM",
        ("app.services.persona", "PERSONA_UPDATES_SYSTEM"),
        optimizable=True,
        llm_feature="persona_updates",
    ),
    _s(
        4,
        "persona_compare",
        "人设差异复核",
        "persona",
        "人设差异复核提示词：判断增量档案与全量重算档案在人设覆盖度上是否等价并打分 0-100，"
        "作为增量是否采用的第二道放行条件。",
        "人设增量 vs 全量对齐校验",
        "app/services/persona.py:105 · PERSONA_COMPARE_SYSTEM",
        ("app.services.persona", "PERSONA_COMPARE_SYSTEM"),
        optimizable=True,
        llm_feature="persona_compare",
    ),
    _s(
        5,
        "persona_init.contract",
        "人设逐篇提取契约",
        "persona",
        "人设逐篇提取的输出 JSON 契约：固定 tags[] 与 redlines[] 字段及维度枚举（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['persona_init']",
        None,
        category="contract",
        editable=False,
    ),
    _s(
        6,
        "persona_merge.contract",
        "人设归纳合并契约",
        "persona",
        "人设归纳合并的输出 JSON 契约：固定 tags[]/redlines[] 四层档案结构（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['persona_merge']",
        None,
        category="contract",
        editable=False,
    ),
    _s(
        7,
        "persona_updates.contract",
        "人设增量合并契约",
        "persona",
        "人设增量合并的输出 JSON 契约：固定四层档案结构（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['persona_updates']",
        None,
        category="contract",
        editable=False,
    ),
    _s(
        8,
        "persona_compare.contract",
        "人设差异复核契约",
        "persona",
        "人设差异复核的输出 JSON 契约：固定 score/reason 字段（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['persona_compare']",
        None,
        category="contract",
        editable=False,
    ),
    # ---------- 模块 5｜素材导入 ----------
    _s(
        1,
        "video_tags",
        "视频预打标",
        "material",
        "视频预打标提示词：按转写稿判断赛道（可多选）、是否商务广告、给自定义标签，用于素材入库自动确认。",
        "导入流水线 ASR 完成后预打标（import_video_task）",
        "app/services/persona.py:113 · VIDEO_TAGS_SYSTEM",
        ("app.services.persona", "VIDEO_TAGS_SYSTEM"),
        optimizable=True,
        llm_feature="video_tags",
    ),
    _s(
        2,
        "correct",
        "转写校对",
        "material",
        "转写校对提示词：结合原视频文案修正 ASR 转写中的错别字与行业术语，保持口语原样、不增删内容，"
        "输出纯文本修正稿。",
        "导入流水线 ASR 成功后转写校对",
        "app/services/ingest.py:62 · CORRECT_SYSTEM",
        ("app.services.ingest", "CORRECT_SYSTEM"),
        optimizable=True,
        llm_feature="correct",
    ),
    _s(
        3,
        "video_tags.contract",
        "视频预打标契约",
        "material",
        "视频预打标的输出 JSON 契约：固定 main_topics/is_ad/tags 字段（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['video_tags']",
        None,
        category="contract",
        editable=False,
    ),
    _s(
        4,
        "correct.contract",
        "转写校对契约",
        "material",
        "转写校对的输出契约：只输出修正后的纯文本，不要 JSON/解释（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['correct']",
        None,
        category="contract",
        editable=False,
    ),
    # ---------- 模块 6｜改稿学习 ----------
    _s(
        1,
        "diff",
        "改稿差异学习",
        "learning",
        "改稿差异学习提示词：对比同一篇稿子的逐版修改，提炼作者反复在改什么、往哪个方向改，"
        "产出可确认的人设风格建议。",
        "草稿修改/定稿后改稿差异分析任务",
        "app/services/diff_analysis.py:24 · DIFF_SYSTEM",
        ("app.services.diff_analysis", "DIFF_SYSTEM"),
        optimizable=True,
        llm_feature="diff",
    ),
    _s(
        2,
        "feedback_insight",
        "稿件反馈复盘",
        "learning",
        "稿件反馈复盘提示词：结合作者认可/否定结论、亲笔评价与逐版演进，分析这篇稿为什么好/差，"
        "输出 2~4 句可迁移心得写回反馈记录，供生成时参考。",
        "草稿状态变为完成/不采用后的反馈分析任务",
        "app/services/feedback_analysis.py:35 · ANALYSIS_SYSTEM",
        ("app.services.feedback_analysis", "ANALYSIS_SYSTEM"),
        llm_feature="feedback_analysis",
    ),
    _s(
        3,
        "diff.contract",
        "改稿差异契约",
        "learning",
        "改稿差异的输出 JSON 契约：固定 suggestions[] 的 label/description/reason 字段（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['diff']",
        None,
        category="contract",
        editable=False,
    ),
    # ---------- 模块 7｜视频复盘 ----------
    _s(
        1,
        "video_review",
        "视频复盘归因",
        "review",
        "视频复盘归因提示词：只能依据输入的真实指标、文案原句和评论原文解释这条视频为什么好或差，"
        "不得编造数字/行业均值，样本少时不得断言。",
        "视频复盘分析（POST /api/douyin-review/analyze → 后台任务）",
        "app/services/video_review_attribution.py:43 · SYSTEM",
        ("app.services.video_review_attribution", "SYSTEM"),
        optimizable=True,
        llm_feature="video_review",
    ),
    _s(
        2,
        "video_review_advice",
        "视频按指标优化建议",
        "review",
        "视频复盘按指标优化建议提示词：结合指标差距与文案原句，给出可执行的优化建议；"
        "对比基线是作者自己近 30 条作品，禁止引用行业平均等无依据数据。",
        "视频复盘分析中的「按指标优化建议」步骤",
        "app/services/video_review_advices.py:30 · SYSTEM",
        ("app.services.video_review_advices", "SYSTEM"),
        llm_feature="video_review",
    ),
    _s(
        3,
        "video_review.contract",
        "视频复盘归因契约",
        "review",
        "视频复盘归因的输出 JSON 契约：固定 findings[] 的维度/结论/建议/判定类型/指标键/文案原句字段（只读展示）。",
        "视频复盘分析（程序拼接进 user 消息）",
        "app/services/prompt_contract.py · CONTRACTS['video_review']",
        None,
        category="contract",
        editable=False,
    ),
    _s(
        4,
        "video_review_advice.contract",
        "视频建议契约",
        "review",
        "视频复盘按指标优化建议的输出 JSON 契约：固定 advices[] 的维度/原因/动作/文案依据字段（只读展示）。",
        "视频复盘分析（程序拼接进 user 消息）",
        "app/services/prompt_contract.py · CONTRACTS['video_review_advice']",
        None,
        category="contract",
        editable=False,
    ),
    # ---------- 模块 8｜AI 对话 ----------
    _s(
        1,
        "chat",
        "AI 对话主提示词",
        "chat",
        "AI 对话主提示词：定义作者数据助手角色、可查数据范围、工具使用方法与「写操作必须先取得作者同意」的权限边界；"
        "运行时程序会追加工具数据规则、数据字典与创作模式段。",
        "POST /api/chat 与 /api/chat/stream",
        "app/services/chat_service.py:27 · SYSTEM_PROMPT",
        ("app.services.chat_service", "SYSTEM_PROMPT"),
        optimizable=True,
        llm_feature="chat",
    ),
    _s(
        2,
        "chat_create_mode",
        "创作共创模式段",
        "chat",
        "AI 对话创作共创模式追加段：当作者选择创作模式时，把助手从「查数据」切到开放式共创"
        "（允许发散、追问、多方向），数据规则与写操作确认规则仍有效。",
        "AI 对话创作模式（mode=create）",
        "app/services/chat_service.py:511 · CREATE_MODE_PROMPT",
        ("app.services.chat_service", "CREATE_MODE_PROMPT"),
        llm_feature="chat",
    ),
    _s(
        3,
        "chat.contract",
        "AI 对话契约",
        "chat",
        "AI 对话的输出契约：用简体中文、简洁口语化回答；涉及生成/修改/删除的写操作必须先取得作者明确同意（只读展示）。",
        "提示词优化候选拼接与自检（运行时不从表读）",
        "app/services/prompt_contract.py · CONTRACTS['chat']",
        None,
        category="contract",
        editable=False,
    ),
    # ---------- 模块 9｜选题灵感 ----------
    _s(
        1,
        "ideas_match",
        "热点×人设选题匹配",
        "ideas",
        "每日选题匹配提示词：从今日热点列表里挑出最匹配作者人设和赛道的选题并改写成更贴合作者的标题，"
        "输出候选标题/平台/分数/理由 JSON；用于每日流水线候选不足时的兜底。",
        "每日流水线候选匹配（无候选兜底）",
        "app/services/pipeline.py · MATCH_SYSTEM",
        ("app.services.pipeline", "MATCH_SYSTEM"),
        llm_feature="ideas",
    ),
    _s(
        2,
        "ideas_daily_ai",
        "每日 AI 建议选题",
        "ideas",
        "每日 AI 选题提示词：基于作者人设、今日热榜、评论区高频提问与赛道缺口，给出一条作者适合讲又可能出圈的选题，"
        "输出标题/分数/理由 JSON。",
        "每日流水线 AI 选题槽",
        "app/services/pipeline.py · DAILY_AI_SYSTEM",
        ("app.services.pipeline", "DAILY_AI_SYSTEM"),
        llm_feature="ideas",
    ),
    _s(
        3,
        "ideas_daily_best",
        "今日最佳选题评选",
        "ideas",
        "今日最佳选题评选提示词：从当天已生成候选里按「人设契合度 × 热度/传播潜力」选出一条最适合今天开拍的，"
        "输出编号与理由 JSON。",
        "每日「今日最佳」推送",
        "app/services/pipeline.py · DAILY_BEST_SYSTEM",
        ("app.services.pipeline", "DAILY_BEST_SYSTEM"),
        llm_feature="ideas",
    ),
    _s(
        4,
        "ideas_angles",
        "选题 3 个切入角度",
        "ideas",
        "选题切入角度提示词：针对作者给出的选题输出 3 个不同切入角度（标题/开头钩子/为什么能火）JSON；"
        "用于脚本工作台的「生成角度」。",
        "POST /api/drafts/angles",
        "app/api/drafts.py · ANGLES_SYSTEM",
        ("app.api.drafts", "ANGLES_SYSTEM"),
        llm_feature="ideas",
    ),
    _s(
        5,
        "inspiration_refine",
        "随手记提炼选题",
        "ideas",
        "灵感随手记提炼提示词：把作者随手记的一句观察/经历/想法提炼成一个可直接写口播稿的选题标题"
        "（≤30 字、有钩子、贴赛道）。",
        "POST /api/inspiration/{note_id}/develop",
        "app/services/inspiration.py:9 · _SYSTEM",
        ("app.services.inspiration", "_SYSTEM"),
        llm_feature="ideas",
    ),
    # ---------- 模块 10｜内容机会 ----------
    _s(
        1,
        "opportunity_comment_cluster",
        "观众提问榜聚类",
        "opportunity",
        "观众提问榜聚类提示词：把评论区原话按同一类问题/诉求归组，产出规范化、可直接当选题的问题标题并按需求强度排序，"
        "过滤赞美与广告。",
        "内容机会·观众提问榜（POST /api/opportunities/comments、定时任务）",
        "app/services/opportunity.py:245 · _LLM_CLUSTER_SYSTEM",
        ("app.services.opportunity", "_LLM_CLUSTER_SYSTEM"),
        llm_feature="ideas",
    ),
    _s(
        2,
        "opportunity_gap",
        "缺口选题",
        "opportunity",
        "缺口选题提示词：基于作者人设、最近讲过的话题与近期热点，给出「该讲但还没讲过」的选题并说明缺口依据，"
        "避免重复与宽泛大词。",
        "内容机会·缺口选题（POST /api/opportunities/gap、定时任务、对话工具）",
        "app/services/opportunity.py:510 · _GAP_SYSTEM",
        ("app.services.opportunity", "_GAP_SYSTEM"),
        llm_feature="ideas",
    ),
    # ---------- 模块 11｜素材检索 ----------
    _s(
        1,
        "evidence_pick",
        "联网参考选文",
        "evidence",
        "联网参考选文提示词：让生成方模型按主博主人设从候选文章中挑出 2~3 篇能提供具体事实/数据/案例/反常识观点的参考，"
        "营销卖课引流一律不选，并给出选择理由。",
        "生成/洗稿的联网证据层（选文）",
        "app/services/evidence.py:75 · _PICK_SYSTEM",
        ("app.services.evidence", "_PICK_SYSTEM"),
        llm_feature="generation",
    ),
    # ---------- 模块 12｜草稿元信息 ----------
    _s(
        1,
        "draft_meta",
        "标题封面标签生成",
        "draft_meta",
        "标题封面标签生成提示词：根据脚本正文与作者人设，生成 5 条视频标题、5 条封面字、5 条素材标签候选。",
        "POST /api/drafts/{id}/suggest-meta",
        "app/services/draft_meta_suggest.py:12 · SUGGEST_META_SYSTEM",
        ("app.services.draft_meta_suggest", "SUGGEST_META_SYSTEM"),
        llm_feature="draft_meta",
    ),
    # ---------- 模块 13｜提示词优化 ----------
    _s(
        1,
        "prompt_optimize",
        "提示词优化器",
        "prompt_ops",
        "提示词优化器系统提示词：约束优化器只改「角色与任务」部分，不得改动作者事实/红线/输出契约与字段名，"
        "输出优化后的提示词正文与变更说明。",
        "提示词优化后台任务（prompt_optimize）",
        "app/services/prompt_service.py:42 · OPT_SYSTEM",
        ("app.services.prompt_service", "OPT_SYSTEM"),
        llm_feature="prompt_optimize",
    ),
    # ---------- 模块 14｜系统自检 ----------
    _s(
        1,
        "selfcheck_probe_chat",
        "自检-文本对话探针",
        "selfcheck",
        "模型兼容性自检（文本探针）提示词：用一句极简指令验证模型能否正常返回非空文本；"
        "只用于「AI 设置」里的双模型兼容性自检，不参与业务功能。",
        "模型兼容性自检（保存模型配置后）",
        "app/services/model_health.py · SELFCHECK_PROBE_CHAT_SYSTEM",
        ("app.services.model_health", "SELFCHECK_PROBE_CHAT_SYSTEM"),
        category="probe",
        editable=False,
    ),
    _s(
        2,
        "selfcheck_probe_json",
        "自检-JSON 输出探针",
        "selfcheck",
        "模型兼容性自检（JSON 探针）提示词：要求模型严格输出 {\"ok\":true}，验证模型是否支持 JSON 输出契约；"
        "只用于「AI 设置」里的双模型兼容性自检。",
        "模型兼容性自检（保存模型配置后）",
        "app/services/model_health.py · SELFCHECK_PROBE_JSON_SYSTEM",
        ("app.services.model_health", "SELFCHECK_PROBE_JSON_SYSTEM"),
        category="probe",
        editable=False,
    ),
]

SPEC_BY_KEY: dict[str, PromptSpec] = {spec.key: spec for spec in PROMPT_SPECS}

# 现有 10 个页面可编辑/可优化 key（AI 优化与金样本评测先只对这些开放）
OPTIMIZABLE_KEYS: frozenset[str] = frozenset(s.key for s in PROMPT_SPECS if s.optimizable)

_MODULE_ORDER: dict[str, int] = {name: i for i, (name, _label) in enumerate(MODULES)}


def get_spec(key: str) -> PromptSpec | None:
    return SPEC_BY_KEY.get(key)


def default_content(key: str) -> str:
    """代码默认正文（种子/兜底）。惰性 import 业务常量，避免循环导入；失败返回空串。"""
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        return ""
    if spec.category == "contract":
        try:
            from . import prompt_contract

            contract_key = key[: -len(".contract")] if key.endswith(".contract") else key
            return str(prompt_contract.CONTRACTS.get(contract_key, ""))
        except Exception:  # noqa: BLE001 契约取不到不阻断
            return ""
    if spec.default_ref is None:
        return ""
    module_name, attr = spec.default_ref
    try:
        return str(getattr(import_module(module_name), attr))
    except Exception:  # noqa: BLE001 代码常量缺失时返回空串，由 get_prompt 继续降级
        return ""


def sorted_specs() -> list[PromptSpec]:
    """按模块顺序 + 模块内序号排好序的注册表。"""
    return sorted(PROMPT_SPECS, key=lambda s: (s.sort_order, s.key))


__all__ = [
    "MODULES",
    "MODULE_LABELS",
    "OPTIMIZABLE_KEYS",
    "PROMPT_SPECS",
    "PromptSpec",
    "SPEC_BY_KEY",
    "default_content",
    "get_spec",
    "sorted_specs",
]
