"""邮件推送：QQ SMTP（每日选题 + 失败告警）。未配置/配置非法时安全跳过（开发模式）。

R-140：邮件是**次要通道**，它的失败不能反过来把「已经生成好的稿子」判为失败——
之前 `server.login` 抛 `UnicodeEncodeError` 会把整轮流水线置 failed（3 篇稿子白生成、还报 failed）。
现在：
1. `mail_config_problem()` 提前校验（缺失 / 非 ASCII 占位符 / 不是邮箱）并给出可读原因；
2. `_send` 把 SMTP 异常收敛成「记录日志 + 返回 False」，不再向上抛；
3. 调用方（流水线）把原因写进 `run.error` 与完成通知，做到「不静默、不炸穿」。
"""

from __future__ import annotations

import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.digest import build_digest_html, build_failure_html
from ..core.log import get_logger
from ..models.hot_topic import TopicCandidate

log = get_logger("notify")


def mail_config_problem(settings=None) -> str:
    """邮件配置是否可用；返回可读原因（空串 = 可用）。"""
    s = settings or get_settings()
    user = str(getattr(s, "smtp_user", "") or "").strip()
    code = str(getattr(s, "smtp_auth_code", "") or "").strip()
    to = str(getattr(s, "mail_to", "") or "").strip()
    if not (user and code and to):
        return "未配置 SMTP（.env 需填 ECHO_SMTP_USER / ECHO_SMTP_AUTH_CODE / ECHO_MAIL_TO）"
    bad = [
        name
        for name, value in (
            ("ECHO_SMTP_USER", user),
            ("ECHO_SMTP_AUTH_CODE", code),
            ("ECHO_MAIL_TO", to),
        )
        if not value.isascii()
    ]
    if bad:
        return (
            "、".join(bad)
            + " 含非 ASCII 字符（多半是 .env 里直接抄了说明文字/占位符未替换），请填真实值"
        )
    if "@" not in to:
        return f"ECHO_MAIL_TO 不是合法邮箱：{to[:40]}"
    return ""


def _send(subject: str, html: str, settings=None) -> bool:
    """发信；返回是否真正发出。配置非法或发送失败都返回 False（原因见日志/调用方）。"""
    settings = settings or get_settings()
    problem = mail_config_problem(settings)
    if problem:
        log.warning("邮件未发送：%s", problem)
        return False
    msg = MIMEMultipart("alternative")
    # 中文主题必须 RFC2047 编码（不编码的话 smtplib 会在 ASCII 编码阶段炸掉）；纯 ASCII 保持原样
    msg["Subject"] = subject if subject.isascii() else Header(subject, "utf-8").encode()
    msg["From"] = settings.smtp_user
    msg["To"] = settings.mail_to
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.login(settings.smtp_user, settings.smtp_auth_code)
            server.sendmail(settings.smtp_user, [settings.mail_to], msg.as_bytes())
    except Exception as exc:  # noqa: BLE001 邮件失败不该炸穿调用方（流水线/定时任务）
        log.exception("邮件发送失败：%s", exc)
        return False
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
