"""Email notification service using SMTP.

Sends cron job completion notifications to the user's registered email.
Disabled by default — enable via PLATFORM_ENABLE_EMAIL_NOTIFICATION=true
plus the PLATFORM_SMTP_* settings.  SMTP credentials live only in the
gateway process (same security model as LLM API keys); user containers
never see them, they only POST a completion callback with their token.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape as html_escape

from app.config import settings

logger = logging.getLogger(__name__)

FROM_DISPLAY_NAME = "个人智能助手"
# Email-side display cap (the container hook caps the wire payload at the same size).
MAX_RESULT_CHARS = 65535


def build_cron_completion_email(
    job_name: str, session_url: str, success: bool, result_text: str = ""
) -> tuple[str, str]:
    """Return (subject, html_body) for a cron completion notification."""
    status = "执行完成" if success else "执行失败"
    subject = f"[定时任务{status}] {job_name}"
    result_text = (result_text or "").strip()
    tail_word = "结果" if success else "详情"
    if result_text:
        sentence = (
            f"您的定时任务「{job_name}」已{status}，下面正文显示了部分内容，"
            f"详情请点击下方链接到会话中查看{tail_word}："
        )
    else:
        sentence = f"您的定时任务「{job_name}」已{status}，请点击下方链接到会话中查看{tail_word}："
    # 链接放在正文引用块上面：先给入口，再给内容摘登
    html = f"<p>{sentence}</p>" f'<p><a href="{session_url}">{session_url}</a></p>'
    if result_text:
        truncated = len(result_text) > MAX_RESULT_CHARS
        shown = result_text[:MAX_RESULT_CHARS]
        tail = "\n……（内容过长已截断，完整内容请打开会话查看）" if truncated else ""
        html += (
            '<pre style="white-space:pre-wrap;background:#f6f7f9;border:1px solid #e3e6ea;'
            'border-radius:6px;padding:12px;font-size:13px;line-height:1.6;">'
            f"{html_escape(shown + tail)}</pre>"
        )
    return subject, html


def _send_smtp(to_addr: str, subject: str, html_body: str) -> None:
    """Blocking SMTP send — run via asyncio.to_thread, never on the event loop."""
    from_addr = settings.smtp_from or settings.smtp_user

    msg = MIMEText(html_body, "html", "utf-8")
    msg["From"] = formataddr((str(Header(FROM_DISPLAY_NAME, "utf-8")), from_addr))
    msg["To"] = to_addr
    msg["Subject"] = Header(subject, "utf-8")

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            try:
                server.starttls()
            except smtplib.SMTPNotSupportedError:
                pass  # plain-text SMTP (trusted internal network)
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())


async def send_email(to_addr: str, subject: str, html_body: str) -> None:
    await asyncio.to_thread(_send_smtp, to_addr, subject, html_body)


async def notify_cron_completed(
    user_email: str, job_name: str, session_url: str, success: bool, result_text: str = ""
) -> None:
    """Send a cron completion email; never raises — notification must not break cron flow."""
    if not settings.enable_email_notification:
        logger.debug("Email notification disabled (PLATFORM_ENABLE_EMAIL_NOTIFICATION=false), skipping")
        return
    if not settings.smtp_host:
        logger.warning("Email notification enabled but PLATFORM_SMTP_HOST is empty, skipping")
        return
    # 收件人覆盖：配了统一收件人则所有邮件发给他，没配才发给任务主人
    to_addr = settings.notify_override_email.strip() or user_email
    if not to_addr:
        logger.warning("Cron completion notify skipped: no override configured and user has no email on file")
        return

    subject, html = build_cron_completion_email(job_name, session_url, success, result_text)
    try:
        logger.info("📧 Cron notify email TO=%s Subject=%s", to_addr, subject)
        await send_email(to_addr, subject, html)
        logger.info("✅ Cron notify email sent to %s", to_addr)
    except Exception as exc:
        # Email is best-effort: log and swallow
        logger.error("❌ Failed to send cron notify email to %s: %s", to_addr, exc, exc_info=True)
