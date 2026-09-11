"""邮件推送：QQ SMTP（每日选题 + 失败告警）。未配置 SMTP 时安全跳过（开发模式）。"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.digest import build_digest_html, build_failure_html
from ..models.hot_topic import TopicCandidate


def _send(subject: str, html: str, settings=None) -> bool:
    settings = settings or get_settings()
    if not (settings.smtp_user and settings.smtp_auth_code and settings.mail_to):
        return False  # 未配置 SMTP，开发模式跳过
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = settings.mail_to
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.login(settings.smtp_user, settings.smtp_auth_code)
        server.sendmail(settings.smtp_user, [settings.mail_to], msg.as_string())
    return True


def send_daily_digest(db: Session, run_date: str, settings=None) -> bool:
    """发送某天选题邮件；返回是否真正发出（False=未配置 SMTP）。"""
    settings = settings or get_settings()
    candidates = (
        db.query(TopicCandidate)
        .filter(TopicCandidate.run_date == run_date)
        .order_by(TopicCandidate.score.desc())
        .all()
    )
    from ..models.draft import Draft

    items = []
    for c in candidates:
        draft = db.get(Draft, c.draft_id) if c.draft_id else None
        items.append(
            {
                "title": c.title,
                "platform": c.platform,
                "score": c.score,
                "reason": c.reason,
                "draft_id": c.draft_id,
                "cover_text": draft.cover_text if draft else "",
                "script": draft.script if draft else "",
            }
        )
    html = build_digest_html(items, settings.web_base_url)
    subject = f"【echo】今日选题与脚本（{run_date}）"
    return _send(subject, html, settings)


def send_failure_alert(db: Session, run: object, settings=None) -> bool:
    settings = settings or get_settings()
    html = build_failure_html(str(getattr(run, "error", "未知错误")))
    subject = f"【echo】今日流水线运行失败（{getattr(run, 'run_date', '')}）"
    return _send(subject, html, settings)


def send_alert(subject: str, detail: str, settings=None) -> bool:
    """通用失败告警（R-133）：定时任务/后台任务失败时用；未配置 SMTP 时返回 False。"""
    settings = settings or get_settings()
    html = build_failure_html(detail)
    return _send(f"【echo】{subject}", html, settings)
