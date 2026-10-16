"""数据库：SQLite + SQLAlchemy 2.x（含 R-016 轻量 schema 迁移）。

注：项目文档写的是 Alembic，但代码库尚未落地 Alembic 脚手架；
R-016 起先用幂等轻量迁移保证旧库可升级，后续再补 Alembic（tech-debt）。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    path: Path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},  # 多线程同步时避免 database is locked
    )

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        """R-163：并行消费者并发读写 —— 开 WAL（读写不互斥）+ busy_timeout + synchronous=NORMAL。"""
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_videos() -> None:
    """videos 表：platform/main_topic（单值）→ platforms/main_topics（JSON 数组）+ cover_path。

    幂等：只在旧列存在/新列缺失时执行；全新库（create_all 已建新结构）自动跳过。
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(videos)").fetchall()}
        adds = []
        if "title" not in cols:
            adds.append("title VARCHAR(255) NOT NULL DEFAULT ''")
        if "platforms" not in cols:
            adds.append("platforms TEXT NOT NULL DEFAULT '[]'")
        if "main_topics" not in cols:
            adds.append("main_topics TEXT NOT NULL DEFAULT '[]'")
        if "cover_path" not in cols:
            adds.append("cover_path VARCHAR(255) NOT NULL DEFAULT ''")
        # M13（R-027/R-029）：素材归属主博主 + 绑定云端作品
        if "creator_id" not in cols:
            adds.append("creator_id INTEGER REFERENCES creators(id)")
        if "platform_post_id" not in cols:
            adds.append("platform_post_id VARCHAR(200) NOT NULL DEFAULT ''")
        if "ad_price" not in cols:
            adds.append("ad_price INTEGER")
        if "work_id" not in cols:
            adds.append("work_id INTEGER REFERENCES works(id)")
        for ddl in adds:
            conn.exec_driver_sql(f"ALTER TABLE videos ADD COLUMN {ddl}")

        # 旧列存在：回填后删除
        if "platform" in cols and "main_topic" in cols:
            rows = conn.exec_driver_sql("SELECT id, platform, main_topic FROM videos").fetchall()
            for vid, platform, main_topic in rows:
                platforms = json.dumps([platform]) if platform else "[]"
                main_topics = json.dumps([main_topic]) if main_topic else "[]"
                conn.execute(
                    text("UPDATE videos SET platforms = :p, main_topics = :m WHERE id = :id"),
                    {"p": platforms, "m": main_topics, "id": vid},
                )
            try:
                conn.exec_driver_sql("ALTER TABLE videos DROP COLUMN platform")
                conn.exec_driver_sql("ALTER TABLE videos DROP COLUMN main_topic")
            except Exception:
                # SQLite 版本过低无法删列时保留旧列（新列已生效，无碍使用）
                pass


def _migrate_account_avatars() -> None:
    """M13：creator_accounts 增加头像列（手动上传/自动同步）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(creator_accounts)").fetchall()}
        adds = []
        if "avatar_path" not in cols:
            adds.append("avatar_path VARCHAR(255) NOT NULL DEFAULT ''")
        if "avatar_url" not in cols:
            adds.append("avatar_url VARCHAR(1000) NOT NULL DEFAULT ''")
        for ddl in adds:
            conn.exec_driver_sql(f"ALTER TABLE creator_accounts ADD COLUMN {ddl}")


def _migrate_feedback_dims() -> None:
    """R-030②：feedback 增加四维分节评分列。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(feedback)").fetchall()}
        adds = []
        for col in ("hook_score", "pace_score", "ending_score", "style_score"):
            if col not in cols:
                adds.append(f"{col} INTEGER")
        for ddl in adds:
            conn.exec_driver_sql(f"ALTER TABLE feedback ADD COLUMN {ddl}")


def _migrate_feedback_insight() -> None:
    """R-211：feedback 增加 insight 列（状态流转触发分析的 LLM 心得）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(feedback)").fetchall()}
        if "insight" not in cols:
            conn.exec_driver_sql("ALTER TABLE feedback ADD COLUMN insight TEXT NOT NULL DEFAULT ''")


def _migrate_topic_candidate_slot() -> None:
    """R-073：topic_candidates 增加 slot 列（comment|hot|ai）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(topic_candidates)").fetchall()}
        if "slot" not in cols:
            conn.exec_driver_sql("ALTER TABLE topic_candidates ADD COLUMN slot VARCHAR(10) NOT NULL DEFAULT ''")


def _migrate_topic_idea_likes() -> None:
    """R-072：topic_ideas 增加 likes 列（按来源评论点赞排序）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(topic_ideas)").fetchall()}
        if "likes" not in cols:
            conn.exec_driver_sql("ALTER TABLE topic_ideas ADD COLUMN likes INTEGER NOT NULL DEFAULT 0")


def _migrate_sync_progress() -> None:
    """R-070：sync_jobs 增加进度列（done/total/note），供博主页进度条轮询。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sync_jobs)").fetchall()}
        adds = []
        if "progress_total" not in cols:
            adds.append("progress_total INTEGER NOT NULL DEFAULT 0")
        if "progress_done" not in cols:
            adds.append("progress_done INTEGER NOT NULL DEFAULT 0")
        if "progress_note" not in cols:
            adds.append("progress_note VARCHAR(255) NOT NULL DEFAULT ''")
        for ddl in adds:
            conn.exec_driver_sql(f"ALTER TABLE sync_jobs ADD COLUMN {ddl}")


def _migrate_comment_likes() -> None:
    """R-067：platform_post_comments 增加评论点赞数列（按点赞 Top50 入库/展示）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(platform_post_comments)").fetchall()}
        if "likes" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_post_comments ADD COLUMN likes INTEGER NOT NULL DEFAULT 0")


def _migrate_creator_scope() -> None:
    """M13（R-029）：drafts / persona_tags 增加 creator_id（素材 creator_id 已在 _migrate_videos）。"""
    with engine.begin() as conn:
        # platform_posts 增加 work_id（跨平台合并）
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(platform_posts)").fetchall()}
        if "work_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_posts ADD COLUMN work_id INTEGER REFERENCES works(id)")
        if "tags" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_posts ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        if "is_ad" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_posts ADD COLUMN is_ad BOOLEAN NOT NULL DEFAULT 0")
        if "ad_price" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_posts ADD COLUMN ad_price INTEGER")
    with engine.begin() as conn:
        for table in ("drafts", "persona_tags"):
            cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
            if "creator_id" not in cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN creator_id INTEGER REFERENCES creators(id)"
                )


def _migrate_chat() -> None:
    """chat_messages 增加 conversation_id；存量消息归入默认会话。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chat_messages)").fetchall()}
        if "conversation_id" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE chat_messages ADD COLUMN conversation_id INTEGER REFERENCES chat_conversations(id) ON DELETE CASCADE"
            )
        if conn.exec_driver_sql("SELECT COUNT(*) FROM chat_conversations").fetchone()[0] == 0:
            if conn.exec_driver_sql("SELECT COUNT(*) FROM chat_messages").fetchone()[0] > 0:
                conn.exec_driver_sql(
                    "INSERT INTO chat_conversations (title, created_at, updated_at) VALUES ('默认对话', datetime('now'), datetime('now'))"
                )
        first_id = conn.exec_driver_sql(
            "SELECT id FROM chat_conversations ORDER BY id LIMIT 1"
        ).fetchone()
        if first_id:
            conn.exec_driver_sql(
                "UPDATE chat_messages SET conversation_id = :cid WHERE conversation_id IS NULL",
                {"cid": first_id[0]},
            )




def _migrate_transcript_asr_model() -> None:
    """R-113 补充：transcripts 增加 asr_model，并回填历史硅基流动所用模型（Qwen3）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(transcripts)").fetchall()}
        if "asr_model" not in cols:
            conn.exec_driver_sql("ALTER TABLE transcripts ADD COLUMN asr_model VARCHAR(100) NOT NULL DEFAULT ''")
        model = get_settings().siliconflow_asr_model or "Qwen/Qwen3-ASR-1.7B"
        conn.exec_driver_sql(
            "UPDATE transcripts SET asr_model = ? WHERE asr_provider = 'siliconflow' AND asr_model = ''",
            (model,),
        )

def _migrate_transcript_asr_provider() -> None:
    """R-112：transcripts 增加 asr_provider（mock|aliyun|siliconflow），并回填历史来源。

    历史规则：2026-09-07 之前全部为阿里云 ASR；09-07 起切换到硅基流动（阿里云当时 OSS 已停用）。
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(transcripts)").fetchall()}
        if "asr_provider" not in cols:
            conn.exec_driver_sql("ALTER TABLE transcripts ADD COLUMN asr_provider VARCHAR(20) NOT NULL DEFAULT ''")
        conn.exec_driver_sql(
            "UPDATE transcripts SET asr_provider = 'aliyun' WHERE asr_provider = '' AND created_at < '2026-09-07'"
        )
        conn.exec_driver_sql(
            "UPDATE transcripts SET asr_provider = 'siliconflow' WHERE asr_provider = '' AND created_at >= '2026-09-07'"
        )


def _migrate_task_result() -> None:
    """R-116：background_tasks 增加 result（后台任务结果 JSON）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(background_tasks)").fetchall()}
        if "result" not in cols:
            conn.exec_driver_sql("ALTER TABLE background_tasks ADD COLUMN result TEXT NOT NULL DEFAULT ''")


def _migrate_draft_source_ref() -> None:
    """R-117：drafts 增加 source_ref（记录洗稿来源素材）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drafts)").fetchall()}
        if "source_ref" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN source_ref TEXT NOT NULL DEFAULT '{}'")


def _migrate_draft_tags() -> None:
    """R-120：drafts 增加 tags（素材标签）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drafts)").fetchall()}
        if "tags" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")

def _migrate_task_note() -> None:
    """background_tasks 增加 note（阶段说明），R-081。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(background_tasks)").fetchall()}
        if "note" not in cols:
            conn.exec_driver_sql("ALTER TABLE background_tasks ADD COLUMN note VARCHAR(255) NOT NULL DEFAULT ''")


def _migrate_persona_dimension() -> None:
    """R-128：persona_tags 增加 dimension（AI 自定人设维度，如语气/价值观/口头禅）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(persona_tags)").fetchall()}
        if "dimension" not in cols:
            conn.exec_driver_sql("ALTER TABLE persona_tags ADD COLUMN dimension VARCHAR(30) NOT NULL DEFAULT ''")


def _migrate_persona_layer() -> None:
    """R-182：persona_tags 四层重构——layer/evidence/frequency/last_seen_at/confirm_strength。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(persona_tags)").fetchall()}
        if "layer" not in cols:
            conn.exec_driver_sql("ALTER TABLE persona_tags ADD COLUMN layer VARCHAR(20) NOT NULL DEFAULT 'stance'")
        if "evidence" not in cols:
            conn.exec_driver_sql("ALTER TABLE persona_tags ADD COLUMN evidence TEXT NOT NULL DEFAULT ''")
        if "frequency" not in cols:
            conn.exec_driver_sql("ALTER TABLE persona_tags ADD COLUMN frequency INTEGER NOT NULL DEFAULT 0")
        if "last_seen_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE persona_tags ADD COLUMN last_seen_at DATETIME")
        if "confirm_strength" not in cols:
            conn.exec_driver_sql("ALTER TABLE persona_tags ADD COLUMN confirm_strength INTEGER NOT NULL DEFAULT 1")


def _migrate_draft_prompt_version() -> None:
    """R-129 M116：drafts 增加 prompt_version（生成时启用的提示词版本，便于按版本归因反馈）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drafts)").fetchall()}
        if "prompt_version" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN prompt_version INTEGER NOT NULL DEFAULT 0")


def _migrate_draft_persona_version() -> None:
    """R-130/R-131：drafts 增加 persona_version（生成时的人设版本）与 quality（生成后自检结果 JSON）。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drafts)").fetchall()}
        if "persona_version" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN persona_version INTEGER NOT NULL DEFAULT 0")
        if "quality" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN quality TEXT NOT NULL DEFAULT '{}'")


def _migrate_draft_publish() -> None:
    """R-184：drafts 增加发布回填字段 publish_url/publish_platform/published_at。"""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drafts)").fetchall()}
        if "publish_url" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN publish_url VARCHAR(500) NOT NULL DEFAULT ''")
        if "publish_platform" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN publish_platform VARCHAR(20) NOT NULL DEFAULT ''")
        if "published_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN published_at DATETIME")
        if "performance" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN performance TEXT NOT NULL DEFAULT '{}'")
        if "work_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE drafts ADD COLUMN work_id INTEGER REFERENCES works(id)")


def _migrate_sunset_review() -> None:
    """R-136：复盘功能正式下线——删除 review_reports 表与 review 提示词行。

    复盘 ABCD 的 API 与前端页面已在 R-097 删除，generate_report 成为孤儿函数、表恒空；
    作者确认「正式下线」，故清理死表与死提示词（赛道雷达能力已迁到 services/metrics.radar）。
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS review_reports")
        try:
            conn.exec_driver_sql("DELETE FROM ai_prompts WHERE key = 'review'")
        except Exception:  # noqa: BLE001 老库可能还没有 ai_prompts 表
            pass


def _fix_video_creator_binding() -> None:
    """R-082：自动下载的本地素材归属错挂修复。

    原因：R-077 建本地素材时用了“全局当前主博主”，若同步的是其它博主(如马甲号/对标)的作品，
    视频会被挂到错误博主名下，导致切到正确博主看不到文件、点卡片跳到别的博主。
    修复规则：有 work 绑定 → 跟随 work.creator_id；否则跟随首个 local_video_id 绑定帖的账号博主。
    """
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            UPDATE videos SET creator_id = (
                SELECT w.creator_id FROM works w WHERE w.id = videos.work_id
            )
            WHERE videos.work_id IS NOT NULL
              AND videos.creator_id IS NOT NULL
              AND (SELECT w.creator_id FROM works w WHERE w.id = videos.work_id) IS NOT NULL
              AND videos.creator_id != (SELECT w.creator_id FROM works w WHERE w.id = videos.work_id)
            """
        )
        conn.exec_driver_sql(
            """
            UPDATE videos SET creator_id = (
                SELECT ca.creator_id FROM platform_posts pp
                  JOIN creator_accounts ca ON ca.id = pp.account_id
                 WHERE pp.local_video_id = videos.id ORDER BY pp.id LIMIT 1
            )
            WHERE videos.work_id IS NULL
              AND videos.creator_id IS NOT NULL
              AND (SELECT ca.creator_id FROM platform_posts pp
                     JOIN creator_accounts ca ON ca.id = pp.account_id
                    WHERE pp.local_video_id = videos.id ORDER BY pp.id LIMIT 1) IS NOT NULL
              AND videos.creator_id != (SELECT ca.creator_id FROM platform_posts pp
                     JOIN creator_accounts ca ON ca.id = pp.account_id
                    WHERE pp.local_video_id = videos.id ORDER BY pp.id LIMIT 1)
            """
        )


def _auto_confirm_tags() -> None:
    """R-083：存量 AI 预打标签素材自动确认（tags_confirmed=1）。"""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            UPDATE videos SET tags_confirmed = 1
            WHERE tags_confirmed = 0 AND tags IS NOT NULL AND tags != '[]'
              AND EXISTS (
                SELECT 1 FROM transcripts t
                WHERE t.video_id = videos.id AND t.asr_status = 'done'
                  AND (t.transcript_text != '' OR t.corrected_text != '')
              )
            """
        )


def _ensure_indexes() -> None:
    """补常见查询缺的索引（幂等：已存在跳过）。"""
    wanted = {
        "platform_posts": {
            "ix_platform_posts_local_video_id": "local_video_id",
            "ix_platform_posts_publish_time": "publish_time",
        },
        "videos": {"ix_videos_platform_post_id": "platform_post_id"},
        "notifications": {"ix_notifications_created_at": "created_at"},
    }
    with engine.begin() as conn:
        for table, idxs in wanted.items():
            try:
                existing = {
                    row[1] for row in conn.exec_driver_sql(f"PRAGMA index_list({table})").fetchall()
                }
            except Exception:  # noqa: BLE001  表可能不存在（新库 create_all 已建）
                continue
            for name, col in idxs.items():
                if name not in existing:
                    try:
                        conn.exec_driver_sql(
                            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})"
                        )
                    except Exception:  # noqa: BLE001  单索引失败不阻断启动
                        pass


def _ensure_binding_integrity() -> None:
    """R-061-D-1：平台作品↔本地素材绑定收敛为单事实源(local_video_id)。

    - 去重：同一 (local_video_id, platform) 只保留最早一条绑定
    - 反向补全：videos.platform_post_id 指向的作品若未绑定则补绑
    - 唯一部分索引：防未来再次产生重复绑定
    """
    with engine.begin() as conn:
        try:
            dups = conn.exec_driver_sql(
                "SELECT local_video_id, platform, MIN(id) FROM platform_posts "
                "WHERE local_video_id IS NOT NULL GROUP BY local_video_id, platform HAVING COUNT(*)>1"
            ).fetchall()
            for local_video_id, platform, keep_id in dups:
                conn.exec_driver_sql(
                    "UPDATE platform_posts SET local_video_id=NULL WHERE local_video_id=? AND platform=? AND id<>?",
                    (local_video_id, platform, keep_id),
                )
        except Exception:  # noqa: BLE001 表可能尚未创建
            pass
        try:
            rows = conn.exec_driver_sql(
                "SELECT id, platform_post_id FROM videos WHERE platform_post_id != '' AND platform_post_id LIKE '%:%'"
            ).fetchall()
            for video_id, key in rows:
                platform, ext = key.split(":", 1)
                conn.exec_driver_sql(
                    "UPDATE platform_posts SET local_video_id=? WHERE platform=? AND platform_post_id=? AND local_video_id IS NULL",
                    (video_id, platform, ext),
                )
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_platform_posts_local_platform "
                "ON platform_posts(local_video_id, platform) WHERE local_video_id IS NOT NULL"
            )
        except Exception:  # noqa: BLE001 唯一冲突则在前面已去重；残余异常不阻断启动
            pass


def _fix_platform_timezone() -> None:
    """一次性迁移：历史 platform 时间按 UTC 存储，改为北京时间(+8)。

    迁移范围：platform_posts.publish_time，以及由平台转本地产生
    （有 platform_post_id/work_id）的 videos.published_at；用户手动填的本地时间不受影响。
    """
    from .models.kv import Kv

    session = SessionLocal()
    try:
        row = session.get(Kv, "platform_tz_migrated_v1")
        if row is not None and row.value == "1":
            return
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE platform_posts SET publish_time = datetime(publish_time, '+8 hours') "
                "WHERE publish_time IS NOT NULL"
            )
            conn.exec_driver_sql(
                "UPDATE videos SET published_at = datetime(published_at, '+8 hours') "
                "WHERE (platform_post_id != '' OR work_id IS NOT NULL) AND published_at IS NOT NULL"
            )
        if row is None:
            session.add(Kv(key="platform_tz_migrated_v1", value="1"))
        else:
            row.value = "1"
        session.commit()
    finally:
        session.close()


def _fix_app_utc_columns() -> None:
    """一次性迁移：历史用 datetime.utcnow 写入的应用时间列（通知/任务/素材/草稿…）是 UTC，
    统一 +8h 迁移为北京时间。范围=ORM 中 default 为本应用 now 的 DateTime 列 + 手动赋值列。"""
    from sqlalchemy import DateTime

    from .models.kv import Kv

    session = SessionLocal()
    try:
        row = session.get(Kv, "app_tz_migrated_v1")
        if row is not None and row.value == "1":
            return
        targets: set[tuple[str, str]] = set()
        for meta in Base.metadata.sorted_tables:
            for col in meta.columns:
                if not isinstance(col.type, DateTime):
                    continue
                d = col.default
                # SQLAlchemy 会包装 default 函数（非同一对象），按模块/名字识别本应用 now
                if d is not None:
                    fn = getattr(d, "arg", None)
                    if getattr(fn, "__module__", "") == "app.core.timeutil" and getattr(fn, "__name__", "") == "now":
                        targets.add((meta.name, col.name))
        # 手动赋值（无 default）的应用时间列
        targets.update({("sync_jobs", "finished_at"), ("creator_accounts", "last_sync_at")})
        with engine.begin() as conn:
            for tname, cname in targets:
                try:
                    conn.exec_driver_sql(
                        f"UPDATE {tname} SET {cname} = datetime({cname}, '+8 hours') "
                        f"WHERE {cname} IS NOT NULL"
                    )
                except Exception:  # noqa: BLE001 单列迁移失败不阻断启动
                    pass
        if row is None:
            session.add(Kv(key="app_tz_migrated_v1", value="1"))
        else:
            row.value = "1"
        session.commit()
    finally:
        session.close()


def _migrate_discussion_model_fields() -> None:
    """R-178：draft_discussions 记录**实际出结果**的模型（used_slot/vendor/model_id）。

    之前只存槽位名（`actor=model1/model2`），作者切了模型后历史留痕就无从考证；
    新列对历史行留空（前端显示「未记录模型（历史）」），不伪造。
    """
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(draft_discussions)").fetchall()}
        if "used_slot" not in cols:
            conn.exec_driver_sql("ALTER TABLE draft_discussions ADD COLUMN used_slot VARCHAR(20) NOT NULL DEFAULT ''")
        if "vendor" not in cols:
            conn.exec_driver_sql("ALTER TABLE draft_discussions ADD COLUMN vendor VARCHAR(40) NOT NULL DEFAULT ''")
        if "model_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE draft_discussions ADD COLUMN model_id VARCHAR(80) NOT NULL DEFAULT ''")


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    # R-144 D：迁移记账表（模型已注册，create_all 会建；这里显式确保一次，便于单独调用）
    from .core import schema_guard

    schema_guard.ensure_migrations_table(engine)
    _ensure_indexes()
    _ensure_binding_integrity()
    _migrate_videos()
    _migrate_creator_scope()
    _migrate_account_avatars()
    _migrate_feedback_dims()
    _migrate_feedback_insight()
    _migrate_chat()
    _migrate_comment_likes()
    _migrate_sync_progress()
    _migrate_topic_idea_likes()
    _migrate_topic_candidate_slot()
    _migrate_task_note()
    _migrate_persona_dimension()
    _migrate_persona_layer()
    _migrate_draft_prompt_version()
    _migrate_draft_persona_version()
    _migrate_sunset_review()
    _migrate_task_result()
    _migrate_draft_source_ref()
    _migrate_draft_tags()
    _migrate_draft_publish()
    _migrate_transcript_asr_provider()
    _migrate_transcript_asr_model()
    _migrate_discussion_model_fields()
    _fix_video_creator_binding()
    _auto_confirm_tags()
    _fix_app_utc_columns()  # 历史 UTC 时间列一次性 +8h → 北京时间
    # R-021：首次启动把各功能默认提示词 seed 入库（版本 v1）
    from .services.prompt_service import (
        ensure_defaults,
        ensure_enabled_fallback,
        ensure_generation_steering_prompt,
        ensure_persona_layer_prompts,
    )

    session = SessionLocal()
    try:
        ensure_defaults(session)
        ensure_persona_layer_prompts(session)  # R-182：人设四层提示词升级
        ensure_generation_steering_prompt(session)  # R-183：生成提示词退回方向盘
        ensure_enabled_fallback(session)  # R-231：无启用版兜底启用代码默认
    finally:
        session.close()
    _fix_platform_timezone()
    # R-147 P1：只读分析视图（给 AI 对话的 sql_query 用；视图即白名单）
    from .core import analytics_views

    analytics_views.ensure_views(engine)
    # R-144 D：写入基线记录（R-144 之前的所有结构变更已在上面的幂等迁移里跑过）
    schema_guard.ensure_baseline(engine)
