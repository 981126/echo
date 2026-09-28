"""内容导入流水线：转写 → AI 校对 → 预打标签；人设分析（逐篇提取→归纳合并→增量校验）。"""

from __future__ import annotations

import json

from ..config import get_settings
from ..core.transcript import normalize_text
from ..models.persona import PersonaCheck
from ..models.video import Transcript, Video
from . import budget_settings, llm_router, model_settings
from .llm import LLMError
from .persona import PersonaService
from .prompt_service import get_prompt
from .transcription import Transcriber, TranscriptionError
from .creator_service import current_creator_id


def _set_pending_flag(db, value: int) -> None:
    """置「增量人设校验待补跑」标记（R-128）：任务进行中又有新素材导入时用。"""
    from ..models.kv import Kv

    row = db.get(Kv, "persona_incremental_pending")
    if row is None:
        db.add(Kv(key="persona_incremental_pending", value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def enqueue_persona_incremental(db, video=None, creator_id=None) -> int | None:
    """入队「增量人设校验」后台任务（R-128）。

    已有同类任务在跑时不重复入队，只置 pending 标记，由当前任务收尾时补跑一次
    （避免任务执行期间新导入的素材被漏掉）。

    R-180：人设只学**当前主博主**——对标博主/其它博主的素材不进人设（D-028），
    避免为对标博主白白烧 LLM 并堆积永远用不到的待确认建议。
    """
    from ..models.task import BackgroundTask
    from ..tasks import start_task

    owner_id = current_creator_id(db)
    cid = creator_id or (video.creator_id if video is not None else None) or owner_id
    if not owner_id or cid != owner_id:
        return None
    vid = video.id if video is not None else 0
    dup = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.kind == "persona_incremental", BackgroundTask.status.in_(["pending", "running"]))
        .first()
    )
    if dup is not None:
        _set_pending_flag(db, 1)
        return None
    return start_task("persona_incremental", {"creator_id": cid, "video_id": vid}, persona_incremental_task)

CORRECT_SYSTEM = (
    "你是转写校对助手。修正转写稿中的错别字、行业术语（如面试/求职/offer 相关词汇），"
    "保持口语原样，不增删内容。只输出修正后的文本。"
)


def correct_transcript(transcript_text: str, source_text: str = "", llm=None, db=None) -> str:
    """AI 校对：结合原始文案修正 ASR 行业词；无密钥时原样返回。

    R-139：默认走模型1（失败降级模型2）；`llm` 仍可注入（测试/显式指定）。
    """
    text = normalize_text(transcript_text)
    if not text:
        return ""
    llm = llm or llm_router.primary_llm(db, "correct")
    try:
        user = f"原始文案（仅供参考，可能与口播不一致）：\n{source_text or '无'}\n\n转写稿：\n{text}"
        corrected = llm.chat(
            [
                {"role": "system", "content": get_prompt("correct")},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=budget_settings.budget_for(db, "correct"),
        )
        return normalize_text(corrected) or text
    except LLMError:
        return text


def import_video_task(db, payload: dict) -> None:
    """后台任务：单条视频 转写→校对→预打标签。"""
    video = db.get(Video, int(payload["video_id"]))
    if video is None:
        return
    settings = get_settings()
    asr = model_settings.asr_config(db)  # R-138：ASR 走运行时配置 → 保存即生效

    if video.transcript is None or (
        not video.transcript.transcript_text and video.transcript.asr_status != "done"
    ):
        path = settings.videos_dir / video.filename
        transcriber = Transcriber(settings, mode=asr["mode"], model=asr["model"])
        try:
            text = transcriber.transcribe(path)
        except TranscriptionError as exc:
            # R-094：转写失败也落 asr_status=failed，并给可读原因
            model = asr["model"] if asr["mode"] == "siliconflow" else ""
            if video.transcript is None:
                video.transcript = Transcript(video_id=video.id, asr_status="failed", asr_provider=asr["mode"], asr_model=model)
                db.add(video.transcript)
            else:
                video.transcript.asr_status = "failed"
                video.transcript.asr_provider = asr["mode"]
                video.transcript.asr_model = model
            db.commit()
            msg = str(exc) or "转写失败"
            if "识别结果为空" in msg:
                msg += "（未识别到有效语音：视频可能无声/只有背景音乐/音量过低或音轨异常，可检查该视频音轨后重试）"
            raise TranscriptionError(msg) from exc
        corrected = correct_transcript(text, db=db)
        if video.transcript is None:
            db.add(
                Transcript(
                    video_id=video.id,
                    transcript_text=text,
                    corrected_text=corrected,
                    asr_status="done",
                    asr_provider=asr["mode"],
                    asr_model=asr["model"] if asr["mode"] == "siliconflow" else "",
                )
            )
        else:
            video.transcript.transcript_text = text
            video.transcript.corrected_text = corrected
            video.transcript.asr_status = "done"
            video.transcript.asr_provider = asr["mode"]
            video.transcript.asr_model = asr["model"] if asr["mode"] == "siliconflow" else ""
        db.commit()
        db.refresh(video)

    transcript = video.transcript
    if transcript:
        text = transcript.corrected_text or transcript.transcript_text
        if not video.tags_confirmed:
            try:
                suggestion = PersonaService().suggest_video_tags(text)
                if suggestion.get("main_topics"):
                    video.main_topics = json.dumps(suggestion["main_topics"], ensure_ascii=False)
                video.is_ad = suggestion["is_ad"]
                video.tags = json.dumps(suggestion["tags"], ensure_ascii=False)
                video.tags_confirmed = True  # R-083：AI 预打标签自动确认，不再要求逐条点「确认标签」
                db.commit()
            except Exception:
                # 预打标签失败不影响转写结果；保持 tags_confirmed=False 待后续重试/手填
                db.rollback()
        # 人设增量校验（广告视频不参与）：后台做「增量 + 全量重算对照」（R-128）
        if not video.is_ad:
            try:
                enqueue_persona_incremental(db, video=video)
            except Exception:
                db.rollback()


def _owner_materials(db, cid: int | None) -> list[tuple[Video, str]]:
    """当前主博主的非广告、有转写稿素材（优先校对稿）。"""
    vq = db.query(Video).filter(Video.is_ad.is_(False))
    if cid:
        vq = vq.filter(Video.creator_id == cid)
    out: list[tuple[Video, str]] = []
    for v in vq.all():
        if not v.transcript:
            continue
        text = v.transcript.corrected_text or v.transcript.transcript_text
        if text:
            out.append((v, text))
    return out


def _pick_new_text(materials: list[tuple[Video, str]], payload: dict) -> str:
    """挑出本次增量要并进去的那篇：优先 payload 指定素材，否则取最新一条。"""
    vid = int(payload.get("video_id") or 0)
    if vid:
        for v, text in materials:
            if v.id == vid:
                return text
    return materials[-1][1]


def persona_init_task(db, payload: dict, update=None) -> dict:
    """后台任务：逐篇提炼 → AI 归纳合并去重 → 生成人设建议（R-126/R-128）。

    每篇一次调用（4 路并行，结果按内容缓存），再用 persona_merge 提示词做一次
    「总结去重」归纳成结构化档案（维度由 AI 自定），跳过已确认/待确认同标签后落库。
    """
    from . import persona_profile

    # R-180：人设只分析当前主博主，纠正历史遗留/异常入队的其它博主 cid。
    owner_id = current_creator_id(db)
    cid = payload.get("creator_id") or owner_id
    if owner_id and cid != owner_id:
        cid = owner_id
    materials = _owner_materials(db, cid)
    if not materials:
        return {"message": "没有可用转写稿，未产出人设建议"}
    total = len(materials)
    texts = [t for _v, t in materials]
    if update:
        update(3, f"逐篇分析人设（0/{total}）…")

    def _progress(done: int, todo: int) -> None:
        if update:
            update(min(80, 5 + int(75 * done / max(todo, 1))), f"逐篇分析人设（{done}/{todo}）…")

    parts = persona_profile.extract_pieces(db, texts, service_factory=lambda: PersonaService(), progress=_progress)
    if update:
        update(88, f"AI 归纳合并去重（{total} 篇）…")
    profile = persona_profile.merge_profile(parts, service_factory=lambda: PersonaService())
    persona_profile.annotate_profile_stats(profile, parts, materials)
    res = persona_profile.persist_suggestions(db, cid, profile, skip_existing=True)
    tail = "（已达上限被截断，建议先确认后再跑一次）" if res.get("truncated") else ""
    if update:
        update(100, f"完成：新增建议 {res['added']} 条（版本 v{res['version']}）{tail}")
    return {"message": f"新增待确认人设建议 {res['added']} 条（v{res['version']}）{tail}"}


def persona_incremental_task(db, payload: dict, update=None) -> dict:
    """后台任务：增量更新人设，并与「从头全量重算」结果做 5% 对齐校验（R-128）。

    流程：全量重算（逐篇提炼→AI 归纳合并）→ 增量（当前档案 + 新篇）→
    集合覆盖率 + AI 语义复核 → 达标用增量、不达标自动回退全量并通知 → 落库校验记录。
    """
    from . import persona_profile

    # R-180：人设只分析当前主博主，纠正历史遗留/异常入队的其它博主 cid。
    owner_id = current_creator_id(db)
    cid = payload.get("creator_id") or owner_id
    if owner_id and cid != owner_id:
        cid = owner_id
    materials = _owner_materials(db, cid)
    if not materials:
        return {"message": "没有可用转写稿，跳过人设增量校验"}
    total = len(materials)
    texts = [t for _v, t in materials]
    if update:
        update(3, f"全量重算对照（0/{total}）…")

    def _progress(done: int, todo: int) -> None:
        if update:
            update(min(60, 5 + int(55 * done / max(todo, 1))), f"全量重算对照（{done}/{todo}）…")

    # 1) 全量重算：逐篇提炼（按内容缓存，等价于从头重跑）→ AI 归纳合并
    parts = persona_profile.extract_pieces(db, texts, service_factory=lambda: PersonaService(), progress=_progress)
    if update:
        update(66, f"全量档案归纳合并（{total} 篇）…")
    full = persona_profile.merge_profile(parts, service_factory=lambda: PersonaService())
    # 2) 增量：当前已确认档案 + 本次新文案
    new_text = _pick_new_text(materials, payload)
    new_part = persona_profile.extract_pieces(db, [new_text], service_factory=lambda: PersonaService())[0]
    current = persona_profile.current_profile(db, cid)
    if update:
        update(76, "增量合并（当前档案 + 新篇）…")
    incremental = persona_profile.incremental_profile(
        current, new_part, service_factory=lambda: PersonaService()
    )
    # 3) 集合覆盖 + AI 语义复核
    if update:
        update(86, "增量 vs 全量对齐校验…")
    verdict = persona_profile.compare_profiles(incremental, full, service_factory=lambda: PersonaService())
    persona_profile.annotate_profile_stats(verdict["chosen"], parts, materials)
    res = persona_profile.persist_suggestions(db, cid, verdict["chosen"], skip_existing=True)
    db.add(
        PersonaCheck(
            creator_id=cid,
            mode="manual" if payload.get("manual") else "increment",
            source_count=total,
            coverage=verdict["coverage"],
            semantic=verdict["semantic"],
            passed=verdict["passed"],
            fallback=verdict["fallback"],
            detail=json.dumps(
                {
                    "missing": verdict["missing"],
                    "semantic_reason": verdict["semantic_reason"],
                    "suggested_version": res["version"],
                    "added": res["added"],
                    "truncated": res.get("truncated", False),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    pct = verdict["coverage"] * 100
    sem_txt = f"、语义分 {verdict['semantic']:.0f}" if verdict["semantic"] is not None else "、语义复核不可用"
    if verdict["fallback"]:
        from ..tasks import push_notification

        push_notification(
            db,
            kind="persona_check",
            status="done",
            title="人设增量差异超标，已回退全量",
            message=(
                f"增量档案覆盖率 {pct:.1f}%{sem_txt}，低于 95%，"
                f"已改用从头全量分析结果（缺失 {len(verdict['missing'])} 项）"
            ),
            target="/persona",
        )
    if update:
        update(100, f"完成：覆盖率 {pct:.1f}%{sem_txt}，新增建议 {res['added']} 条")
    _rerun_if_pending(db, cid)
    tail = "（已达上限被截断）" if res.get("truncated") else ""
    return {
        "message": (
            f"覆盖率 {pct:.1f}%{sem_txt}，"
            + ("已回退为全量结果" if verdict["fallback"] else "增量结果通过")
            + f"，新增建议 {res['added']} 条{tail}"
        )
    }


def _diff_labels(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    """R-182 差异单：按近义匹配算「新增」（新有旧无）与「过期」（旧有新无）。"""
    from .persona import label_match

    added = [n for n in new if not any(label_match(n, o) for o in old)]
    expired = [o for o in old if not any(label_match(o, n) for n in new)]
    return added, expired


def persona_rebuild_task(db, payload: dict, update=None) -> dict:
    """R-182 方案B：推倒重建人设档案。

    清空当前主博主全部人设标签 → 全量逐篇提取 → 四层归纳合并 → 重建为**待确认建议**，
    并写一条 PersonaCheck 差异单（新增/过期/分层计数）。清空前的档案由启动备份兜底。
    """
    from ..models.persona import PersonaTag
    from . import persona_profile

    owner_id = current_creator_id(db)
    cid = owner_id or payload.get("creator_id")
    materials = _owner_materials(db, cid)
    if not materials:
        return {"message": "没有可用转写稿，无法重建人设"}
    total = len(materials)
    texts = [t for _v, t in materials]

    old_q = db.query(PersonaTag)
    if cid:
        old_q = old_q.filter(PersonaTag.creator_id == cid)
    old_labels = [t.label for t in old_q.all()]
    for t in old_q.all():
        db.delete(t)
    db.commit()

    if update:
        update(5, f"推倒重建：逐篇分析人设（0/{total}）…")

    def _progress(done: int, todo: int) -> None:
        if update:
            update(min(70, 5 + int(65 * done / max(todo, 1))), f"逐篇分析人设（{done}/{todo}）…")

    parts = persona_profile.extract_pieces(db, texts, service_factory=lambda: PersonaService(), progress=_progress)
    if update:
        update(80, f"四层归纳合并（{total} 篇）…")
    profile = persona_profile.merge_profile(parts, service_factory=lambda: PersonaService())
    persona_profile.annotate_profile_stats(profile, parts, materials)
    res = persona_profile.persist_suggestions(db, cid, profile, skip_existing=False)

    new_labels = [str(t.get("label", "")) for t in profile.get("tags") or [] if isinstance(t, dict)]
    added, expired = _diff_labels(old_labels, new_labels)
    layer_counts: dict[str, int] = {"core_dna": 0, "stance": 0, "mode": 0, "forbidden": 0}
    for t in profile.get("tags") or []:
        layer = str(t.get("layer", "stance"))
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    layer_counts["forbidden"] += len(profile.get("redlines") or [])
    db.add(
        PersonaCheck(
            creator_id=cid,
            mode="rebuild",
            source_count=total,
            coverage=1.0,
            semantic=None,
            passed=True,
            fallback=False,
            detail=json.dumps(
                {
                    "added": added,
                    "expired": expired,
                    "layers": layer_counts,
                    "version": res["version"],
                    "previous_count": len(old_labels),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    if update:
        update(100, f"重建完成：新增 {len(new_labels)} 条待确认（核心 {layer_counts['core_dna']}）")
    return {
        "message": (
            f"人设已推倒重建：清空旧档案 {len(old_labels)} 条，产出待确认 {res['added']} 条"
            f"（核心DNA {layer_counts['core_dna']}／立场 {layer_counts['stance']}／模式 {layer_counts['mode']}／禁区 {layer_counts['forbidden']}），"
            f"过期 {len(expired)} 条"
        )
    }


def _rerun_if_pending(db, cid: int | None) -> None:
    """增量校验期间又有新素材导入（pending 标记）→ 收尾后再补跑一次，避免漏掉新素材。

    R-134：先入队成功再清标记——原实现先清标记再 start_task，start_task 失败时补跑永久丢失。
    """
    from ..models.kv import Kv
    from ..tasks import start_task

    try:
        row = db.get(Kv, "persona_incremental_pending")
        if row is None or row.value != "1":
            return
        start_task("persona_incremental", {"creator_id": cid, "video_id": 0}, persona_incremental_task)
        row.value = "0"
        db.commit()
    except Exception:  # noqa: BLE001 补跑失败不影响本次结果（标记保留，下次仍会补跑）
        db.rollback()
