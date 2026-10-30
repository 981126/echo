"""内容导入流水线：转写 → AI 校对 → 预打标签；人设分析（逐篇提取→归纳合并→增量校验）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..config import get_settings
from ..core.timeutil import now as _app_now
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


# ---------- R-240 S7：转写失败退避（app_kv 计次 + 下次可重试时间，不改表） ----------

ASR_FAIL_COUNT_KEY = "asr_fail_count:{video_id}"
ASR_RETRY_AFTER_KEY = "asr_retry_after:{video_id}"
ASR_GIVE_UP_NOTIFIED_KEY = "asr_give_up_notified:{video_id}"

# 不可自动重试（无语音/音频过长/额度/配置/格式类）→ 大退避（7 天）
_ASR_NON_RETRYABLE_KEYWORDS = (
    "识别结果为空",
    "无有效语音",
    "SUCCESS_WITH_NO_VALID_FRAGMENT",
    "音频为空",
    "音频超过",
    "音频时长超过",
    "超过硅基流动",
    "超过腾讯",
    "额度",
    "资源包",
    "欠费",
    "未开通",
    "未配置",
    "鉴权",
    "格式不支持",
    "文件不存在",
)
# 可自动重试（网络/超时/轮询超时/5xx 等瞬时故障）→ 指数退避
_ASR_RETRYABLE_KEYWORDS = (
    "超时",
    "Timeout",
    "timeout",
    "轮询",
    "网络",
    "连接",
    "TransportError",
    "EOF",
    "429",
    "500",
    "502",
    "503",
    "504",
    "服务端",
    "暂时",
    "稍后重试",
)


def classify_asr_failure(message: str) -> bool:
    """R-240 S7：判断 ASR 失败是否值得自动重试（True=可重试）。

    规则：无语音/音频过长/额度/配置/格式类 → 不可重试（写 7 天大退避，等人工）；
    网络/超时/轮询超时/5xx 等 → 可重试（分钟级指数退避，最多 `asr_max_attempts` 次）；
    未知错误按可重试处理（最终次数用尽照样跳过，不会无限重试）。
    """
    text = str(message or "")
    if any(kind in text for kind in _ASR_NON_RETRYABLE_KEYWORDS):
        return False
    if any(kind in text for kind in _ASR_RETRYABLE_KEYWORDS):
        return True
    return True


def _asr_max_attempts() -> int:
    return max(1, int(getattr(get_settings(), "asr_max_attempts", 3) or 3))


def _asr_kv_get(db, key: str) -> str:
    """读 app_kv（异常一律当「无记录」，不阻断转写主流程）。"""
    try:
        from ..models.kv import Kv

        row = db.get(Kv, key)
        return str(row.value) if row is not None and row.value is not None else ""
    except Exception:  # noqa: BLE001 Kv 异常不阻断主流程（S7）
        return ""


def _asr_kv_set(db, key: str, value: str) -> None:
    try:
        from ..models.kv import Kv

        row = db.get(Kv, key)
        if row is None:
            db.add(Kv(key=key, value=value))
        else:
            row.value = value
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _asr_kv_delete(db, key: str) -> None:
    try:
        from ..models.kv import Kv

        row = db.get(Kv, key)
        if row is not None:
            db.delete(row)
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def asr_fail_count(db, video_id: int) -> int:
    """已记录的自动转写失败次数（无记录=0）。"""
    raw = _asr_kv_get(db, ASR_FAIL_COUNT_KEY.format(video_id=int(video_id)))
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def asr_retry_after(db, video_id: int) -> datetime | None:
    """下次可自动重试时间（无记录=None）。"""
    raw = _asr_kv_get(db, ASR_RETRY_AFTER_KEY.format(video_id=int(video_id)))
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def asr_backoff_reason(db, video_id: int) -> str:
    """当前是否应跳过自动转写；返回原因文案（'' = 可自动重试）。

    命中两类：已达 `asr_max_attempts` 次（放弃自动重试，等人工），
    或处于退避窗口内（`retry_after > now`）。
    """
    vid = int(video_id)
    count = asr_fail_count(db, vid)
    max_attempts = _asr_max_attempts()
    if count >= max_attempts:
        return f"自动转写已失败 {count} 次（上限 {max_attempts}），已跳过；可在素材编辑页手动重试"
    retry_at = asr_retry_after(db, vid)
    if retry_at is not None and retry_at > _app_now():
        return f"转写失败退避中（第 {count} 次失败，{retry_at:%m-%d %H:%M} 后自动重试；可手动重试）"
    return ""


def record_asr_failure(db, video_id: int, message: str) -> None:
    """R-240 S7：记录一次自动转写失败（次数 +1 + 下次可重试时间），异常不阻断主流程。"""
    try:
        vid = int(video_id)
        count = asr_fail_count(db, vid) + 1
        retryable = classify_asr_failure(message)
        delay_hours = min(2 ** min(count, 5), 24) if retryable else 7 * 24  # 指数退避上限 24h
        retry_at = _app_now() + timedelta(hours=delay_hours)
        _asr_kv_set(db, ASR_FAIL_COUNT_KEY.format(video_id=vid), str(count))
        _asr_kv_set(db, ASR_RETRY_AFTER_KEY.format(video_id=vid), retry_at.isoformat())
    except Exception:  # noqa: BLE001 退避记录失败不能拖垮转写任务（S7）
        db.rollback()


def clear_asr_failure(db, video_id: int) -> None:
    """R-240 S7：清零退避（转写成功 / 用户手动重试时调用）。"""
    vid = int(video_id)
    for template in (ASR_FAIL_COUNT_KEY, ASR_RETRY_AFTER_KEY, ASR_GIVE_UP_NOTIFIED_KEY):
        _asr_kv_delete(db, template.format(video_id=vid))


def notify_asr_give_up_once(db, video: Video) -> bool:
    """R-240 S7：自动转写达到上限时只通知一次，提示可手动重试。"""
    try:
        if video is None or video.id is None:
            return False
        vid = int(video.id)
        count = asr_fail_count(db, vid)
        max_attempts = _asr_max_attempts()
        if count < max_attempts:
            return False
        notified_key = ASR_GIVE_UP_NOTIFIED_KEY.format(video_id=vid)
        if _asr_kv_get(db, notified_key):
            return False
        from ..tasks import push_notification

        title = (video.title or video.filename or "素材").strip()[:60]
        push_notification(
            db,
            kind="import_video",
            status="failed",
            title="自动转写已跳过",
            message=(
                f"「{title}」自动转写失败 {count} 次（上限 {max_attempts}），已跳过自动重试；"
                "可在素材编辑页手动转写。"
            ),
            target="/videos",
        )
        _asr_kv_set(db, notified_key, "1")
        return True
    except Exception:  # noqa: BLE001 通知失败不影响主流程（S7）
        db.rollback()
        return False


def _post_asr_llm(db, video_id: int, text: str, asr: dict) -> None:
    """R-240 M8：ASR 落库 +「LLM 校对」∥「LLM 预打标」并发（2 线程、各自独立 Session）。

    - 校对/转写落库失败 → 向上抛（与串行版一致，任务判失败）；
    - 预打标失败只回滚该支路（保持 tags_confirmed=False，下次补），不阻断另一支；
    - 主线程等待两者完成后由调用方 expire 会话再读最新 transcript/tags。
    """
    from concurrent.futures import ThreadPoolExecutor

    from ..db import SessionLocal

    provider = str(asr.get("mode") or "")
    model = str(asr.get("model") or "") if provider in ("siliconflow", "tencent") else ""

    def _correct_and_store() -> None:
        s = SessionLocal()
        try:
            corrected = correct_transcript(text, db=s)
            video = s.get(Video, video_id)
            if video is None:
                raise RuntimeError(f"素材不存在: {video_id}")
            transcript = video.transcript
            if transcript is None:
                s.add(
                    Transcript(
                        video_id=video_id,
                        transcript_text=text,
                        corrected_text=corrected,
                        asr_status="done",
                        asr_provider=provider,
                        asr_model=model,
                    )
                )
            else:
                transcript.transcript_text = text
                transcript.corrected_text = corrected
                transcript.asr_status = "done"
                transcript.asr_provider = provider
                transcript.asr_model = model
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _tag_video() -> None:
        s = SessionLocal()
        try:
            video = s.get(Video, video_id)
            if video is None or video.tags_confirmed:
                return
            suggestion = PersonaService().suggest_video_tags(text)
            if suggestion.get("main_topics"):
                video.main_topics = json.dumps(suggestion["main_topics"], ensure_ascii=False)
            video.is_ad = suggestion["is_ad"]
            video.tags = json.dumps(suggestion["tags"], ensure_ascii=False)
            video.tags_confirmed = True  # R-083：AI 预打标签自动确认，不再要求逐条点「确认标签」
            s.commit()
        except Exception:  # noqa: BLE001 预打标签失败不影响转写结果（保持待后续重试/手填）
            s.rollback()
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="echo-ingest-llm") as ex:
        correct_future = ex.submit(_correct_and_store)
        tag_future = ex.submit(_tag_video)
        correct_future.result()  # 转写落库失败 → 向上抛（现语义）
        try:
            tag_future.result()  # 内部已吞异常；此处兜底，避免线程 bug 拖垮转写任务
        except Exception:  # noqa: BLE001
            pass


def import_video_task(db, payload: dict) -> None:
    """后台任务：单条视频 转写→校对→预打标签。

    R-240：ASR 成功后「LLM 校对」与「LLM 预打标」并发（见 `_post_asr_llm`）；
    自动转写失败按 S7 写 app_kv 退避计数；手动重试（payload 无 auto 标记）忽略退避并清零。
    """
    payload = payload or {}
    video = db.get(Video, int(payload["video_id"]))
    if video is None:
        return
    if not payload.get("auto"):  # R-240 S7：用户手动重试忽略退避并清零失败计数
        clear_asr_failure(db, video.id)
    settings = get_settings()
    asr = model_settings.asr_config(db)  # R-138：ASR 走运行时配置 → 保存即生效
    post_processed = False

    if video.transcript is None or (
        not video.transcript.transcript_text and video.transcript.asr_status != "done"
    ):
        path = settings.videos_dir / video.filename
        transcriber = Transcriber(settings, mode=asr["mode"], model=asr["model"])
        try:
            text = transcriber.transcribe(path)
        except TranscriptionError as exc:
            # R-094：转写失败也落 asr_status=failed，并给可读原因
            model = asr["model"] if asr["mode"] in ("siliconflow", "tencent") else ""
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
            record_asr_failure(db, video.id, msg)  # R-240 S7：记录次数 + 下次可重试时间
            raise TranscriptionError(msg) from exc
        _post_asr_llm(db, video.id, text, asr)  # R-240 M8：校对 ∥ 预打标（独立 Session 并发）
        clear_asr_failure(db, video.id)  # R-240 S7：成功后清退避计数
        db.expire_all()
        fresh = db.get(Video, video.id)
        if fresh is None:
            return
        video = fresh
        post_processed = True

    transcript = video.transcript
    if transcript:
        text = transcript.corrected_text or transcript.transcript_text
        if not post_processed and not video.tags_confirmed:
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


def _notify_auto_confirmed(db, res: dict) -> None:
    """R-208：把本次自动确认进档案的人设建议通知作者（可到人设页撤销）。"""
    from .persona_profile import AUTO_CONFIRM_MIN_FREQ

    n = int(res.get("auto_confirmed") or 0)
    if not n:
        return
    labels = [str(x) for x in (res.get("auto_labels") or [])]
    head = "、".join(labels[:5]) + ("…" if len(labels) > 5 else "")
    from ..tasks import push_notification

    push_notification(
        db,
        kind="persona_auto_confirm",
        status="done",
        title=f"已自动确认 {n} 条人设建议",
        message=(
            f"命中素材 ≥{AUTO_CONFIRM_MIN_FREQ} 篇且与你已确认档案无冲突，已直接进档案参与生成：{head}。"
            "如不认可，可到人设页撤销。"
        ),
        target="/persona",
    )


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
    _notify_auto_confirmed(db, res)
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
    _notify_auto_confirmed(db, res)
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
    并写一条 PersonaCheck 差异单（新增/过期/分层计数）。
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
    _notify_auto_confirmed(db, res)

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


def persona_auto_confirm_backlog_task(db, payload: dict, update=None) -> dict:
    """R-208：一次性清理历史积压的待确认建议。

    用当前素材重算每条建议的命中篇数（内容缓存命中则不重复调 AI），
    再把「非禁区 + 频次达标 + 未被拒绝」的自动确认进档案，其余保持待确认。
    """
    from . import persona_profile

    owner_id = current_creator_id(db)
    cid = payload.get("creator_id") or owner_id
    if owner_id and cid != owner_id:
        cid = owner_id
    # R-208：M13 之前的历史建议 creator_id 为空（不可见脏数据）——归属当前主博主后统一处理
    if cid:
        from ..models.persona import PersonaTag

        orphans = (
            db.query(PersonaTag)
            .filter(PersonaTag.status == "suggested", PersonaTag.creator_id.is_(None))
            .all()
        )
        for t in orphans:
            t.creator_id = cid
        if orphans:
            db.commit()
    materials = _owner_materials(db, cid)
    if not materials:
        return {"message": "没有可用转写稿，跳过待确认建议清理"}
    total = len(materials)
    texts = [t for _v, t in materials]
    if update:
        update(5, f"重算待确认建议频次（{total} 篇）…")

    def _progress(done: int, todo: int) -> None:
        if update:
            update(min(80, 5 + int(75 * done / max(todo, 1))), f"重算频次（{done}/{todo}）…")

    parts = persona_profile.extract_pieces(db, texts, service_factory=lambda: PersonaService(), progress=_progress)
    if update:
        update(88, "按规则自动确认高置信建议…")
    res = persona_profile.auto_confirm_backlog(db, cid, parts, materials)
    if update:
        update(100, f"完成：检查 {res['checked']} 条，自动确认 {res['confirmed']} 条")
    return {"message": f"待确认建议清理：检查 {res['checked']} 条，自动确认 {res['confirmed']} 条"}


_BACKLOG_DONE_KEY = "persona_auto_confirm_backlog_v1"


def maybe_auto_confirm_backlog_on_startup() -> None:
    """R-208：启动时一次性把存量堆积按同规则处理（Kv 标记保证只跑一次，后台线程执行）。"""
    from ..db import SessionLocal
    from ..models.kv import Kv
    from ..models.persona import PersonaTag

    db = SessionLocal()
    try:
        if db.get(Kv, _BACKLOG_DONE_KEY) is not None:
            return
        if db.query(PersonaTag).filter(PersonaTag.status == "suggested").count() == 0:
            db.add(Kv(key=_BACKLOG_DONE_KEY, value="1"))
            db.commit()
            return
        from ..tasks import start_task

        start_task("persona_auto_confirm_backlog", {}, persona_auto_confirm_backlog_task)
        db.add(Kv(key=_BACKLOG_DONE_KEY, value="1"))
        db.commit()
    except Exception:  # noqa: BLE001 清理是尽力而为，绝不能影响启动
        db.rollback()
    finally:
        db.close()


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
