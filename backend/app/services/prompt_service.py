"""AI 提示词版本服务（R-021）。

每个功能一份提示词，DB 中版本化：
- 默认值懒加载自各服务模块常量（首次启动 seed 入库）
- get_prompt：取当前 enabled 版本
- save：另存为新版本并启用（旧版归档）
- create_candidate：自动优化产出候选（不启用）
- enable：启用指定版本（其余归档）
"""

from __future__ import annotations

import re
from importlib import import_module

from sqlalchemy.orm import Session

from ..models.prompt import AiPrompt


class PromptOptimizeError(RuntimeError):
    """优化不可用或候选自检未通过；携带可读原因供 API 返回给作者（R-129）。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason

# key -> (module, 常量名, 中文名)
PROMPT_META: dict[str, tuple[str, str, str]] = {
    "generation": ("app.services.generation", "GENERATION_SYSTEM", "生成脚本"),
    "persona_init": ("app.services.persona", "PERSONA_INIT_SYSTEM", "人设逐篇提取"),
    "persona_merge": ("app.services.persona", "PERSONA_MERGE_SYSTEM", "人设归纳合并"),
    "video_tags": ("app.services.persona", "VIDEO_TAGS_SYSTEM", "视频预打标"),
    "persona_updates": ("app.services.persona", "PERSONA_UPDATES_SYSTEM", "人设增量合并"),
    "persona_compare": ("app.services.persona", "PERSONA_COMPARE_SYSTEM", "人设差异复核"),
    "diff": ("app.services.diff_analysis", "DIFF_SYSTEM", "改稿差异"),
    "chat": ("app.services.chat_service", "SYSTEM_PROMPT", "AI 对话"),
    "correct": ("app.services.ingest", "CORRECT_SYSTEM", "转写校对"),
}

OPT_SYSTEM = (
    "你是提示词工程专家，正在帮一位自媒体作者优化他自己的 AI 提示词。"
    "你只优化「角色与任务」部分；程序会在你输出之后自动拼接固定的输出契约段。\n"
    "**可以改**：角色设定、写作或判断的方法、结构要求（如开场钩子与收尾引导）、篇幅与语气方向、需要遵守的原则。\n"
    "**不可以改**：作者姓名/身份/学历/收入/经历等具体事实、红线与金句清单、程序解析所需的输出格式与字段名"
    "（这些由系统在运行时动态注入，写进提示词只会重复、过期、失真）。\n"
    "硬性规则：\n"
    "1. 只输出「提示词」正文与「变更说明」，不要 markdown 代码块、不要复述契约段。\n"
    "2. 保持简洁：正文不要超过原提示词的 1.5 倍，能短则短——过长反而锁死 AI 的思路。\n"
    "3. 只给「方向盘」：不要新增过多硬性条数/字数/句式限制。\n"
    "4. 样本只用于理解作者的真实口径与偏好，不要把样本内容原样抄进提示词。"
)


def default_content(key: str) -> str:
    mod_name, attr, _ = PROMPT_META[key]
    return str(getattr(import_module(mod_name), attr))


def label(key: str) -> str:
    return PROMPT_META[key][2]


def get_prompt(key: str, db: Session | None = None) -> str:
    """取当前启用版本的提示词；无记录时回退代码默认值。"""
    from ..db import SessionLocal

    own = db is None
    session: Session = db or SessionLocal()
    try:
        row = (
            session.query(AiPrompt)
            .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
            .order_by(AiPrompt.version.desc())
            .first()
        )
        if row:
            return row.content
    finally:
        if own:
            session.close()
    try:
        return default_content(key)
    except Exception:
        return ""


def ensure_defaults(db: Session) -> None:
    """首次启动把各功能默认提示词 seed 为 v1（enabled）。"""
    for key in PROMPT_META:
        exists = (
            db.query(AiPrompt).filter(AiPrompt.key == key).order_by(AiPrompt.version.desc()).first()
        )
        if exists is None:
            db.add(AiPrompt(key=key, version=1, content=default_content(key), status="enabled", note="系统默认"))
    db.commit()


def _next_version(db: Session, key: str) -> int:
    row = db.query(AiPrompt).filter(AiPrompt.key == key).order_by(AiPrompt.version.desc()).first()
    return (row.version + 1) if row else 1


def ensure_enabled_fallback(db: Session) -> None:
    """R-231：任一提示词 key 无 enabled 版时，兜底另存启用**代码默认**（留痕可回溯）。

    背景：generation v1~v10 曾被操作/自动链路搅成全 archived，运行时静默回退代码默认、
    界面却显示「无启用版本」，作者无法判断当前生效的是哪一版。幂等：已有 enabled 不动。
    """
    for key in PROMPT_META:
        row = (
            db.query(AiPrompt)
            .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
            .first()
        )
        if row is None:
            save_new_version(db, key, default_content(key), note="无启用版本，兜底启用代码默认")


def save_new_version(db: Session, key: str, content: str, note: str = "") -> AiPrompt:
    """手动编辑保存 = 另存为新版本并启用（旧 enabled 转 archived）。"""
    content = (content or "").strip()
    db.query(AiPrompt).filter(AiPrompt.key == key, AiPrompt.status == "enabled").update(
        {"status": "archived"}, synchronize_session=False
    )
    row = AiPrompt(key=key, version=_next_version(db, key), content=content, status="enabled", note=note or "手动编辑")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_candidate(db: Session, key: str, content: str, note: str = "") -> AiPrompt:
    row = AiPrompt(
        key=key, version=_next_version(db, key), content=content, status="candidate", note=note or "AI 自动优化候选"
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# 人设引擎提示词（R-130）：产出物是人设档案，改这些会影响人设提取质量
PERSONA_ENGINE_KEYS = frozenset({"persona_init", "persona_merge", "persona_updates", "persona_compare"})


def prompt_group(key: str) -> str:
    """提示词分组：persona_engine（人设引擎）/ production（生产提示词）。"""
    return "persona_engine" if key in PERSONA_ENGINE_KEYS else "production"


def get_prompt_version(key: str, db: Session) -> int:
    """当前启用版本号（无记录返回 0）；供草稿做「按提示词版本归因」（R-129 M116）。"""
    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )
    return row.version if row else 0


def reject_candidate(db: Session, key: str, version: int) -> AiPrompt | None:
    """拒绝候选（R-129 M116）：只作用于 candidate 状态，留痕不删除。"""
    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.version == version, AiPrompt.status == "candidate")
        .first()
    )
    if row is None:
        return None
    row.status = "rejected"
    db.commit()
    db.refresh(row)
    return row


def version_effect(db: Session, key: str) -> list[dict]:
    """按提示词版本聚合草稿反馈（R-129 M116）：看出哪一版真的产出更受认可的稿子。

    只有 generation 会产出草稿，其它 key 返回空。
    R-211：认可口径改 status 驱动（done=认可 / archived=否定）；历史 rating 仅作参考展示。
    """
    if key != "generation":
        return []
    from ..models.draft import Draft
    from ..models.feedback import Feedback

    fb_by_draft: dict[int, list] = {}
    for fb in db.query(Feedback).all():
        fb_by_draft.setdefault(fb.draft_id, []).append(fb)
    agg: dict[int, dict] = {}
    for d in db.query(Draft).filter(Draft.source == "ai").all():
        ver = d.prompt_version or 0
        row = agg.setdefault(
            ver,
            {"version": ver, "drafts": 0, "rated": 0, "rating_sum": 0, "used": 0, "persona_versions": set()},
        )
        row["drafts"] += 1
        row["persona_versions"].add(d.persona_version or 0)
        if d.status == "done":
            row["used"] += 1  # R-211：完成即认可（历史 liked 口径弃用）
        for fb in fb_by_draft.get(d.id, []):
            if fb.rating:  # 历史评分仅作参考（R-211 起不再产生新评分）
                row["rated"] += 1
                row["rating_sum"] += int(fb.rating)
    out: list[dict] = []
    for _ver, row in sorted(agg.items(), key=lambda kv: kv[0], reverse=True):
        persona_versions = sorted(v for v in row.pop("persona_versions") if v)
        out.append(
            {
                **row,
                "avg_rating": round(row["rating_sum"] / row["rated"], 2) if row["rated"] else None,
                # R-130：同一提示词版本跨越多个人设版本时，均分不能直接横向比较
                "persona_versions": persona_versions,
                "mixed_persona": len(persona_versions) > 1,
            }
        )
    return out


def enable_version(db: Session, key: str, version: int) -> AiPrompt | None:
    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == key, AiPrompt.version == version)
        .first()
    )
    if row is None:
        return None
    db.query(AiPrompt).filter(AiPrompt.key == key, AiPrompt.status == "enabled").update(
        {"status": "archived"}, synchronize_session=False
    )
    row.status = "enabled"
    db.commit()
    db.refresh(row)
    return row


def feedback_context(db: Session) -> str:
    """作者反馈回流（R-211 重构）：status 即反馈信号 + 作者亲笔评价 + LLM 心得。

    - 认可 = 完成（status='done'）的稿；否定 = 不采用（status='archived'）且非纯手写的稿
      （R-210：手写稿被放弃只是作者不想做，不代表写得差，不进负向）。
    - 每条附：作者亲笔评价（comment，如有）+ 复盘心得（feedback.insight，R-211 状态触发的 LLM 分析）。
    - 历史 rating/liked/四维分已弃用，不再参与。
    """
    from ..models.draft import Draft
    from ..models.feedback import Feedback
    from .creator_service import current_creator_id
    from .draft_versions import pure_manual_map

    cid = current_creator_id(db)

    def _drafts_by_status(status: str, limit: int = 5) -> list:
        q = db.query(Draft).filter(Draft.status == status, Draft.script != "")
        if cid:
            q = q.filter(Draft.creator_id == cid)
        return q.order_by(Draft.updated_at.desc()).limit(limit).all()

    highs = _drafts_by_status("done")
    # R-230：负例 = 不采用（archived）+ **删除（deleted）**的 AI 稿——作者真实行为习惯是
    # 直接删稿，原 archived 口径下负反馈几乎为零；纯手写稿仍排除（R-210：放弃手写≠写得差）。
    lows_candidates = _drafts_by_status("archived", limit=20) + _drafts_by_status("deleted", limit=20)
    manual_map = pure_manual_map(db, lows_candidates)
    lows = [d for d in lows_candidates if not manual_map.get(d.id, False)][:5]

    # 每稿最新一条非空 comment / insight（两次小查询，避免逐稿 N+1）
    ids = [d.id for d in highs + lows]
    comments: dict[int, str] = {}
    insights: dict[int, str] = {}
    if ids:
        rows = (
            db.query(Feedback.draft_id, Feedback.comment, Feedback.insight)
            .filter(Feedback.draft_id.in_(ids))
            .order_by(Feedback.id.desc())
            .all()
        )
        for draft_id, comment, insight in rows:
            if draft_id not in comments and (comment or "").strip():
                comments[draft_id] = comment.strip()
            if draft_id not in insights and (insight or "").strip():
                insights[draft_id] = insight.strip()

    def _line(d) -> str:
        text = (d.script or "").strip()
        out = f"- {text[:200]}"
        if comments.get(d.id):
            out += f"\n  作者评价：{comments[d.id][:150]}"
        if insights.get(d.id):
            out += f"\n  复盘心得：{insights[d.id][:200]}"
        # R-209：「AI 原稿→作者改后」diff 仅对 AI 稿展示（手写稿 original_script 语义不同）
        original = (d.original_script or "").strip()
        if d.source == "ai" and original and text and original != text:
            out += f"\n  AI 原稿：{original[:150]}\n  作者改后：{text[:150]}"
        return out

    lines: list[str] = []
    if highs:
        lines.append("作者完成的稿子（认可）——保持这种腔调与结构：")
        lines.extend(_line(d) for d in highs)
    if lows:
        lines.append("作者不采用的稿子——避免这种腔调：")
        lines.extend(_line(d) for d in lows)
    return "\n".join(lines)


def learning_material(db: Session, max_items: int = 16) -> str:
    """组装「提示词优化语料」：人设 + 语言画像 + 全部 ASR 转写文案（按点赞率/互动加权）。

    不再只看最新单条视频：当前所有真实口播文案（优先 ASR 转写）参与，
    点赞率/互动高的权重更高、排更前；人设与红线一并作为优化输入。
    """
    import math
    from datetime import date as _date

    from ..models.metrics import MetricsSnapshot
    from ..models.video import Video
    from .generation import _creator_filter, _persona_context, _style_profile_lines
    from .metrics import _platform_breakdown

    parts: list[str] = []
    cid = _creator_filter(db)

    ctx = _persona_context(db)
    if ctx.get("tags"):
        parts.append("作者人设档案（逐篇提取 + AI 归纳合并，方括号为维度）：\n" + "\n".join(f"- {t}" for t in ctx["tags"]))
    if ctx.get("redlines"):
        parts.append("红线（不要违反）：\n" + "\n".join(f"- {r}" for r in ctx["redlines"]))
    if ctx.get("anchors"):
        parts.append("作者金句锚点：\n" + "\n".join(f"- {a}" for a in ctx["anchors"]))
    try:
        profile = _style_profile_lines(db)
        if profile:
            parts.append("作者语言习惯画像（从全部素材统计）：\n" + profile)
    except Exception:  # noqa: BLE001 画像失败不阻断
        pass

    q = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    snap: dict[int, MetricsSnapshot] = {}
    for _s in db.query(MetricsSnapshot).order_by(MetricsSnapshot.snapshot_date.desc()).all():
        snap.setdefault(_s.video_id, _s)

    scored: list[tuple[float, str, str]] = []
    for v in q.all():
        tr = v.transcript
        if tr is None:
            continue
        text = (tr.corrected_text or tr.transcript_text or "").strip()
        if not text:
            continue
        plays = likes = fav = comments = 0
        for row in _platform_breakdown(db, v):  # 绑定平台最新真实数据
            plays += int(row.get("plays") or 0)
            likes += int(row.get("likes") or 0)
            fav += int(row.get("favorites") or 0)
            comments += int(row.get("comments") or 0)
        if plays <= 0 and likes <= 0:  # 无平台数据退回指标快照
            s = snap.get(v.id)
            if s is not None:
                plays = int(s.plays or 0)
                likes = int(s.likes or 0)
                fav = int(s.favorites or 0)
                comments = int(s.comments or 0)
        rate = min((likes / plays), 1.0) if plays > 0 else 0.0
        engage = plays + likes * 5 + fav * 3 + comments * 10
        base = v.published_at.date() if v.published_at else v.created_at.date()
        age = max((_date.today() - base).days, 0)
        w = (1.0 + math.log1p(engage)) * (1.0 + rate * 3.0) * math.exp(-age / 400.0)
        scored.append((w, text, f"播放{plays} 赞{likes} 藏{fav} 评{comments}"))
    scored.sort(key=lambda x: x[0], reverse=True)

    if scored:
        lines = []
        for i, (_w, text, stat) in enumerate(scored[:max_items], 1):
            lines.append(f"[素材{i}] {stat}：\n{text[:300]}")
        parts.append(
            "作者真实口播文案（全部 ASR 转写，按点赞率/互动加权从高到低，越靠前越该学）：\n"
            + "\n\n".join(lines)
        )
        if len(scored) > max_items:
            parts.append(f"（另有 {len(scored) - max_items} 条，只取权重最高的前 {max_items} 条）")
    return "\n\n".join(parts)


def _optimize_llm(db: Session):
    """优化所用模型（R-139/R-232）：主用槽位走「提示词优化与评测」功能路由——
    默认「跟随生成方」（R-229），可在 AI 设置改选模型1/模型2；失败自动兜底另一槽位。"""
    from . import llm_router

    client = llm_router.primary_llm(db, "prompt_optimize")
    return client, client.used_model


def _strip_fence(text: str) -> str:
    """去掉模型可能包上的 markdown 代码围栏。"""
    body = (text or "").strip()
    match = re.match(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```$", body, re.DOTALL)
    return match.group(1).strip() if match else body


def optimize(db: Session, key: str, material: str = "") -> AiPrompt:
    """产出候选新版（不启用），R-129 口径：

    语料按 key 定制 → 注入输出契约与运行时上下文说明 → 产出后做契约自检（失败重试 1 次）→
    通过与程序固定的契约段拼成完整候选 → 自动排队金样本回放评分。
    样本不足或自检两次都不过时抛 PromptOptimizeError（带可读原因）。
    """
    from . import budget_settings, prompt_contract

    current = get_prompt(key, db)
    if not current:
        raise PromptOptimizeError("当前提示词为空，无法优化")
    if (material or "").strip():
        sources = ["自定义语料"]
    else:
        material, sources = prompt_contract.material_for(key, db)
    if not (material or "").strip():
        raise PromptOptimizeError("样本不足，暂不优化：这个功能还没有可用于学习的真实样本")

    ctx = feedback_context(db)
    user = "\n".join(
        part
        for part in [
            f"当前提示词：\n{current}",
            f"该功能的输出契约（系统固定，程序会原样拼在末尾）：\n{prompt_contract.contract_for(key)}",
            f"运行时上下文说明：{prompt_contract.context_note_for(key)}",
            "作者真实样本（仅用于理解口径，不要抄进提示词）：\n" + "\n\n".join(p for p in [material, ctx] if p and p.strip()),
            "请按下面格式输出，不要解释、不要 markdown 代码块：\n"
            "【提示词】\n"
            "（只写优化后的角色与任务部分，保持简洁，不要超过原提示词的 1.5 倍）\n"
            "【变更说明】\n"
            "（- 改了什么、依据哪条样本或反馈；不超过 3 条）",
        ]
        if part and part.strip()
    )

    limit = prompt_contract.max_candidate_chars(key, current)
    llm, mode = _optimize_llm(db)
    last_reason = ""
    for _attempt in range(2):  # 自检失败自动重试 1 次（R-129 确认口径）
        try:
            raw = llm.chat(
                [{"role": "system", "content": OPT_SYSTEM}, {"role": "user", "content": user}],
                temperature=0.3,
                max_tokens=budget_settings.budget_for(db, "prompt_optimize"),
            )
        except Exception as exc:  # noqa: BLE001 外部失败不破坏当前版
            last_reason = f"AI 服务异常：{str(exc)[:150]}"
            continue
        body, change_note = prompt_contract.split_change_note(_strip_fence(raw))
        if len(body) < 20:  # 只输出了小标题 / 空正文
            last_reason = "候选正文过短（可能只输出了标题）"
            continue
        candidate = prompt_contract.assemble_candidate(key, body)
        if len(candidate) > limit:  # R-132：防膨胀
            last_reason = f"候选过长（{len(candidate)}/{limit} 字），已要求保持简洁"
            continue
        ok, reason = prompt_contract.validate_candidate(key, candidate, db)
        if ok:
            used = getattr(llm, "used_model", "") or mode
            note = f"AI 微调候选（模型 {used}；语料：{prompt_contract.material_summary(sources)}）"
            if change_note:
                note += "\n变更说明：\n" + change_note
            row = create_candidate(db, key, candidate, note=note)
            _start_eval(db, key, row.version)
            return row
        last_reason = reason
    raise PromptOptimizeError(f"候选自检未通过（已重试 1 次）：{last_reason}")


def _start_eval(db: Session, key: str, version: int) -> int | None:
    """候选产出后自动排队金样本回放评分（R-129 M115）；评测失败不影响候选本身。"""
    try:
        from .prompt_eval import start_prompt_eval

        return start_prompt_eval(db, key, version)
    except Exception:  # noqa: BLE001
        return None


def maybe_auto_optimize_prompt(db: Session, threshold: int = 10) -> bool:
    """R-208：素材累计到阈值时**自动**排队提示词优化（不再只发提醒、不需作者手动点）。

    自动产出候选 → 自动跑金样本评测 → 明显更好则自动启用（见 `prompt_eval.prompt_eval_task`）。
    已有同 key 优化任务在跑时跳过本次（计数已清零，下次导入再触发）。返回是否入队。
    """
    from ..models.kv import Kv

    row = db.get(Kv, "generation_import_count")
    if row is None:
        row = Kv(key="generation_import_count", value="0")
        db.add(row)
    cur = int(row.value or "0") + 1
    if cur < threshold:
        row.value = str(cur)
        db.commit()
        return False
    row.value = "0"
    db.commit()
    from ..tasks import find_running_task, push_notification, start_task

    if find_running_task("prompt_optimize", {"key": "generation"}) is not None:
        return False
    start_task("prompt_optimize", {"key": "generation"}, auto_optimize_generation_task)
    push_notification(
        db,
        kind="prompt_optimize",
        status="done",
        title="素材已更新，自动开始优化生成提示词",
        message=f"新增素材累计 {threshold} 条，已自动排队优化「生成脚本」提示词（评测明显更好会自动启用并通知）",
        target="/prompts?key=generation",
    )
    return True


def auto_optimize_generation_task(db: Session, payload: dict, update=None) -> dict:
    """R-208：到量自动优化——样本不足静默跳过，其余失败照常抛给任务层记错。"""
    key = str(payload.get("key") or "generation")
    try:
        row = optimize(db, key)
    except PromptOptimizeError as exc:
        if "样本不足" in str(exc):
            return {"message": f"{label(key)} 样本不足，跳过自动优化"}
        raise
    return {"key": row.key, "version": row.version}


# 规则型提示词（有明确规则、样本可量化）：一键批量优化的对象（R-131）
RULE_KEYS = ("video_tags", "correct", "diff")


def optimize_rule_keys_task(db: Session, payload: dict, update=None) -> dict:
    """手动一键：为有真实样本的规则型 key 各产出一版候选（R-131）。

    自动触发已取消（杠杆在数据侧）；这里保留"能优化规则型提示词"的能力，但由作者主动触发。
    """
    keys = [k for k in (payload.get("keys") or list(RULE_KEYS)) if k in PROMPT_META]
    made: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    total = max(len(keys), 1)
    for i, key in enumerate(keys, 1):
        if update:
            update(int(100 * i / total), f"优化「{label(key)}」…")
        try:
            row = optimize(db, key)
            made.append(f"{label(key)} v{row.version}")
        except PromptOptimizeError as exc:
            if "样本不足" in str(exc):
                skipped.append(label(key))
            else:
                failed.append(f"{label(key)}：{exc}")
    parts = [f"产出候选 {len(made)} 个"]
    if skipped:
        parts.append(f"跳过（样本不足）{len(skipped)} 个")
    if failed:
        parts.append(f"失败 {len(failed)} 个")
    return {"message": "；".join(parts), "made": made, "skipped": skipped, "failed": failed}


def optimize_task(db: Session, payload: dict) -> dict:
    """R-202：单键提示词优化改为后台任务（LLM 较慢）；失败原因经 task.error 回传。"""
    row = optimize(db, str(payload.get("key") or ""), str(payload.get("material") or ""))
    return {"key": row.key, "version": row.version}
