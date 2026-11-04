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

from sqlalchemy.orm import Session

from ..core.log import get_logger
from ..models.prompt import AiPrompt, AiPromptDef
from .prompt_catalog import (
    PROMPT_SPECS,
    SPEC_BY_KEY,
    default_content as _catalog_default_content,
    sorted_specs,
)

log = get_logger("prompt")


class PromptOptimizeError(RuntimeError):
    """优化不可用或候选自检未通过；携带可读原因供 API 返回给作者（R-129）。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# key -> (模块路径, 常量名, 中文名)：由 R-255 注册表派生，保证旧 migration（7a6f…）与测试兼容。
PROMPT_META: dict[str, tuple[str, str, str]] = {
    spec.key: (spec.default_ref[0], spec.default_ref[1], spec.title)
    for spec in PROMPT_SPECS
    if spec.category in ("system", "probe") and spec.default_ref is not None
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
    """代码默认正文（种子/兜底）；未知 key 或常量缺失返回空串。"""
    return _catalog_default_content(key)


def get_spec(key: str):
    """提示词注册信息（R-255）；未知 key 返回 None。"""
    return SPEC_BY_KEY.get(key)


def is_editable(key: str) -> bool:
    spec = SPEC_BY_KEY.get(key)
    return bool(spec and spec.editable)


def is_optimizable(key: str) -> bool:
    spec = SPEC_BY_KEY.get(key)
    return bool(spec and spec.optimizable)


def label(key: str) -> str:
    spec = SPEC_BY_KEY.get(key)
    return spec.title if spec is not None else key


_FALLBACK_WARNED: set[str] = set()


def get_prompt(key: str, db: Session | None = None) -> str:
    """取提示词（R-255 统一读表）。

    优先级：`ai_prompts` 当前启用版本 → `ai_prompt_defs.default_content`（表内默认正文）
    → 代码默认常量 → 空串（同一 key 只警告一次）。DB 不可用/未迁移时自动回退代码默认，
    保证升级前后行为一致、最坏也不会把提示词变空。
    """
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
        if row is not None:
            return row.content
        try:
            definition = (
                session.query(AiPromptDef)
                .filter(AiPromptDef.key == key, AiPromptDef.is_active.is_(True))
                .first()
            )
        except Exception:  # noqa: BLE001 表未迁移/查询失败时继续回退代码默认
            definition = None
        if definition is not None and (definition.default_content or "").strip():
            return definition.default_content
    finally:
        if own:
            session.close()
    fallback = default_content(key)
    if fallback:
        if key not in _FALLBACK_WARNED:
            _FALLBACK_WARNED.add(key)
            log.warning("提示词 %s 库内无启用版本与默认正文，已回退代码常量", key)
        return fallback
    if key not in _FALLBACK_WARNED:
        _FALLBACK_WARNED.add(key)
        log.warning("提示词 %s 无任何可用内容（db/表默认/代码常量均为空）", key)
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


PROMPT_CATALOG_SEED_NOTE = "系统默认（R-255 统一入库补种）"


def ensure_prompt_catalog(db: Session) -> dict[str, int]:
    """R-255 幂等补种：注册表缺登记就补、缺启用版本就补 v1、已有数据一律不动。

    - 每次启动同步 `ai_prompt_defs` 的元数据与 `default_content`（代码默认基准）；
    - `ai_prompts` 只在「该 key 完全没有 enabled 版本」时补 v1，绝不覆盖作者改过的版本；
    - 同时把 R-231 的「无启用版本兜底」接上（此前只被测试调用）。
    """
    from ..core.timeutil import now as _now

    stats = {"registered": 0, "updated": 0, "seeded": 0, "skipped": 0}
    now = _now()
    for spec in sorted_specs():
        content = default_content(spec.key)
        row = db.query(AiPromptDef).filter(AiPromptDef.key == spec.key).first()
        if row is None:
            db.add(
                AiPromptDef(
                    key=spec.key,
                    title=spec.title,
                    module=spec.module,
                    module_label=spec.module_label,
                    purpose=spec.purpose,
                    category=spec.category,
                    editable=spec.editable,
                    optimizable=spec.optimizable,
                    llm_feature=spec.llm_feature,
                    entry=spec.entry,
                    default_content=content,
                    code_ref=spec.code_ref,
                    sort_order=spec.sort_order,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            stats["registered"] += 1
        else:
            desired = {
                "title": spec.title,
                "module": spec.module,
                "module_label": spec.module_label,
                "purpose": spec.purpose,
                "category": spec.category,
                "editable": spec.editable,
                "optimizable": spec.optimizable,
                "llm_feature": spec.llm_feature,
                "entry": spec.entry,
                "default_content": content,
                "code_ref": spec.code_ref,
                "sort_order": spec.sort_order,
                "is_active": True,
            }
            changed = False
            for field, value in desired.items():
                if getattr(row, field) != value:
                    setattr(row, field, value)
                    changed = True
            if changed:
                row.updated_at = now
                stats["updated"] += 1
        if spec.category in ("system", "probe"):
            enabled = (
                db.query(AiPrompt).filter(AiPrompt.key == spec.key, AiPrompt.status == "enabled").first()
            )
            if enabled is None:
                if content.strip():
                    db.add(
                        AiPrompt(
                            key=spec.key,
                            version=1,
                            content=content,
                            status="enabled",
                            note=PROMPT_CATALOG_SEED_NOTE,
                        )
                    )
                    stats["seeded"] += 1
                else:
                    stats["skipped"] += 1
                    log.warning("R-255 注册表补种跳过 %s：代码默认正文为空", spec.key)
    db.commit()
    if stats["registered"] or stats["seeded"]:
        log.info(
            "R-255 提示词注册表补种：新增登记 %s，补启用版本 %s，更新元数据 %s",
            stats["registered"],
            stats["seeded"],
            stats["updated"],
        )
    return stats


# ---------- R-255：video_review 一次性升级为完整系统提示词 ----------

VIDEO_REVIEW_UPGRADE_KV = "r255_video_review_prompt_upgraded"
VIDEO_REVIEW_OLD_SEED = (
    "只能依据输入证据解释视频表现和整理主题，不得创造数字、评论、经历或证据ID。输出必须符合调用方JSON契约。"
)
VIDEO_REVIEW_UPGRADE_NOTE = "R-255 统一入库：video_review 恢复完整系统提示词（旧精简种子归档）"


def upgrade_video_review_prompt(db: Session) -> bool:
    """把 R-237 migration 写入的 54 字精简种子升级为代码完整 SYSTEM；已手改过则不动。"""
    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == "video_review", AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )
    if row is None:
        return False
    if (row.content or "").strip() != VIDEO_REVIEW_OLD_SEED:
        return False
    target = default_content("video_review").strip()
    if not target:
        return False
    old_version = row.version
    save_new_version(db, "video_review", target, note=VIDEO_REVIEW_UPGRADE_NOTE)
    log.info("R-255 video_review 提示词由 v%s 升级为完整版（旧版归档可回退）", old_version)
    return True


def run_r255_video_review_upgrade_once(db: Session) -> bool:
    """执行一次 video_review 升级并写 Kv 标记；已标记返回 False。"""
    from ..models.kv import Kv

    if db.get(Kv, VIDEO_REVIEW_UPGRADE_KV) is not None:
        return False
    changed = upgrade_video_review_prompt(db)
    db.add(Kv(key=VIDEO_REVIEW_UPGRADE_KV, value="1"))
    db.commit()
    if not changed:
        log.info("R-255 video_review 提示词无需升级（已是完整版或已被作者修改），只写一次性标记")
    return changed


def init_prompt_registry_on_startup() -> None:
    """R-255 启动初始化（注册表补种 + video_review 升级）；失败不阻断启动，下次重试。"""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        ensure_prompt_catalog(db)
        run_r255_video_review_upgrade_once(db)
    except Exception:  # noqa: BLE001 初启动失败不阻断服务
        db.rollback()
        log.exception("R-255 提示词注册表启动初始化失败（下次启动重试）")
    finally:
        db.close()


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

    from sqlalchemy.orm import selectinload

    from ..models.metrics import MetricsSnapshot
    from ..models.video import Video
    from .generation import _creator_filter, _persona_context, _style_profile_lines
    from .opportunity import platform_breakdown_map

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

    # R-241 F10：转写稿 selectinload（消 600 次懒加载 N+1）+ 平台数据一次批量预取（原逐视频 3+ 查询）
    q = db.query(Video).options(selectinload(Video.transcript)).filter(Video.is_ad.is_(False))
    if cid:
        q = q.filter(Video.creator_id == cid)
    snap: dict[int, MetricsSnapshot] = {}
    for _s in db.query(MetricsSnapshot).order_by(MetricsSnapshot.snapshot_date.desc()).all():
        snap.setdefault(_s.video_id, _s)

    videos = q.all()
    breakdown_map = platform_breakdown_map(db, videos)
    scored: list[tuple[float, str, str]] = []
    for v in videos:
        tr = v.transcript
        if tr is None:
            continue
        text = (tr.corrected_text or tr.transcript_text or "").strip()
        if not text:
            continue
        plays = likes = fav = comments = 0
        for row in breakdown_map.get(v.id, []):  # 绑定平台最新真实数据
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
                [{"role": "system", "content": get_prompt("prompt_optimize", db)}, {"role": "user", "content": user}],
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


# ---------- R-254：生成提示词一次性放开「参考素材经历归属」 ----------
# 生成文案实际读取 DB 中 enabled 的 generation 版本（代码默认只做兜底）。作者确认放开
# 「对标/他人素材禁止写成作者经历」与 R-228 反编造硬规则，因此部署时把旧句精确替换后
# 另存为新启用版本（旧版归档可回退）。Kv 标记保证只跑一次，失败下次启动重试。

R254_PATCH_DONE_KEY = "r254_generation_prompt_patched"
R254_PATCH_NOTE = "R-254 放开参考素材经历归属（旧版归档可回退）"
R254_GENERATION_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "【对标】素材只能当参考，**禁止写成你自己的经历**；",
        "【对标】素材可以直接使用，也可以把其中的经历、案例、观点写成作者本人的；",
    ),
    (
        "4) 严禁编造具体数字/人名/机构/经历；没有可靠事实就只讲作者的判断，宁可不要数字；",
        "4) 素材不够具体时，允许基于素材补全、扩写细节（包括第一人称经历、具体数字、人物/机构），",
    ),
    (
        "论据缺素材处标【需作者补充】，不要编一个填上；",
        "写成作者能直接录的口播稿即可；",
    ),
    (
        "优先用【站内真实素材·你的】里的真实经历/说法",
        "优先用【站内真实素材】里的真实经历/说法",
    ),
    (
        "观点必须用作者自己的。",
        "观点要按作者本人的口吻和立场表达。",
    ),
)


def patch_generation_prompt_for_r254(db: Session) -> bool:
    """把 enabled 的 generation 提示词按旧句替换后另存新版本（R-254）。返回是否写入新版本。

    只处理命中的旧限制语句；一条都没命中（作者已手改/已是新规则）则不动。
    """
    row = (
        db.query(AiPrompt)
        .filter(AiPrompt.key == "generation", AiPrompt.status == "enabled")
        .order_by(AiPrompt.version.desc())
        .first()
    )
    if row is None:
        return False
    content = row.content or ""
    patched = content
    for old, new in R254_GENERATION_REPLACEMENTS:
        patched = patched.replace(old, new)
    if patched == content:
        return False
    old_version = row.version
    new_row = save_new_version(db, "generation", patched, note=R254_PATCH_NOTE)
    from ..core.log import get_logger

    get_logger("prompt").info("R-254 生成提示词已替换为 v%s（v%s 归档）", new_row.version, old_version)
    return True


def run_r254_prompt_patch_once(db: Session) -> bool:
    """执行一次 R-254 补丁并写 Kv 标记（启动线程与测试共用）；已标记过返回 False。"""
    from ..core.log import get_logger
    from ..models.kv import Kv

    if db.get(Kv, R254_PATCH_DONE_KEY) is not None:
        return False
    changed = patch_generation_prompt_for_r254(db)
    db.add(Kv(key=R254_PATCH_DONE_KEY, value="1"))
    db.commit()
    if not changed:
        get_logger("prompt").info("R-254 生成提示词未命中旧限制语句，跳过（只写一次性标记）")
    return changed


def maybe_patch_r254_generation_prompt_on_startup() -> None:
    """启动时后台跑一次 R-254 提示词补丁；已跑过（Kv 标记）则跳过。"""
    import threading

    from ..core.log import get_logger
    from ..db import SessionLocal
    from ..models.kv import Kv

    logger = get_logger("prompt")
    probe = SessionLocal()
    try:
        if probe.get(Kv, R254_PATCH_DONE_KEY) is not None:
            return
    except Exception:  # noqa: BLE001 读标记失败不阻断启动
        probe.rollback()
    finally:
        probe.close()

    def _run() -> None:
        db = SessionLocal()
        try:
            run_r254_prompt_patch_once(db)
        except Exception:  # noqa: BLE001 补丁失败保留标记缺失，下次启动可重跑
            db.rollback()
            logger.exception("R-254 生成提示词补丁失败（下次启动可重跑）")
        finally:
            db.close()

    threading.Thread(target=_run, name="r254-prompt-patch", daemon=True).start()
