"""Email ingestion for the knowledge base: .msg/.eml -> markdown sidecar page.

Conversion happens ONCE at upload time on the gateway side (this module), so the
in-container knowledge script (pages/search/graph in hermes_knowledge.py) keeps
indexing pure .md files and never pays parsing cost per search. The generated
sidecar page lives next to the original file, e.g. ``foo.msg`` -> ``foo.msg.md``.
The original .msg/.eml remains available as a downloadable attachment.

.msg parsing requires the ``extract-msg`` package (see platform/pyproject.toml);
it is imported lazily so uploads keep working even if the dependency is missing.
.eml parsing uses only the stdlib ``email`` module.
"""

from __future__ import annotations

import email
import email.policy
import html as html_lib
import os
import re
import tempfile

EMAIL_PAGE_EXTENSIONS = (".msg", ".eml")
MAX_BODY_CHARS = 100_000


def is_email_ingest_path(path: str | None) -> bool:
    """True when the given (relative or absolute) path is a .msg/.eml inside a knowledge dir."""
    normalized = (path or "").replace("\\", "/")
    if "/workspace/knowledge/" not in normalized:
        return False
    return normalized.lower().endswith(EMAIL_PAGE_EXTENSIONS)


def sidecar_page_path(path: str) -> str:
    """``foo.msg`` -> ``foo.msg.md`` (same directory)."""
    return f"{path}.md"


def build_email_page_markdown(filename: str, data: bytes) -> str | None:
    """Convert raw .msg/.eml bytes to a knowledge-page markdown. Returns None if unparsable."""
    lower = (filename or "").lower()
    if lower.endswith(".eml"):
        return _parse_eml(filename, data)
    if lower.endswith(".msg"):
        return _parse_msg(filename, data)
    return None


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _truncate_body(text: str) -> str:
    text = (text or "").strip()
    if len(text) > MAX_BODY_CHARS:
        return text[:MAX_BODY_CHARS] + "\n\n……（内容过长已截断，完整内容请查看原始附件）"
    return text


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _build_markdown(
    filename: str,
    subject: str,
    sender: str,
    to: str,
    cc: str,
    date: str,
    body: str,
    attachments: list[str],
) -> str:
    title = _one_line(subject) or filename
    lines = [
        "---",
        f'title: "邮件：{title}"',
        "type: email",
        f'source: "{filename}"',
        "tags: [email]",
    ]
    if date:
        lines.append(f'created: "{date}"')
    lines += [
        "---",
        "",
        f"# 邮件：{title}",
        "",
        f"- 发件人：{sender or '未知'}",
        f"- 收件人：{to or '未知'}",
    ]
    if cc:
        lines.append(f"- 抄送：{cc}")
    if date:
        lines.append(f"- 日期：{date}")
    lines.append(f"- 原始文件：{filename}（可在知识库附件中下载）")
    lines.append(f"- 附件：{', '.join(attachments) if attachments else '无'}")
    lines += ["", "## 正文", "", _truncate_body(body) or "（无正文内容）", ""]
    return "\n".join(lines)


def _parse_eml(filename: str, data: bytes) -> str | None:
    try:
        message = email.message_from_bytes(data, policy=email.policy.default)
    except Exception:
        return None
    subject = _one_line(message.get("Subject", ""))
    sender = _one_line(message.get("From", ""))
    to = _one_line(message.get("To", ""))
    cc = _one_line(message.get("Cc", ""))
    date = _one_line(message.get("Date", ""))

    body = ""
    try:
        preferred = message.get_body(preferencelist=("plain", "html"))
        if preferred is not None:
            content = preferred.get_content()
            if preferred.get_content_type() == "text/html":
                body = _strip_html(content)
            else:
                body = content or ""
    except Exception:
        body = ""

    attachment_names: list[str] = []
    try:
        for part in message.walk():
            try:
                if part.get_content_maintype() == "multipart":
                    continue
                part_name = part.get_filename()
            except Exception:
                part_name = None
            if part_name:
                attachment_names.append(_one_line(part_name))
    except Exception:
        pass

    return _build_markdown(
        filename,
        subject,
        sender,
        to,
        cc,
        date,
        body,
        _dedupe(attachment_names),
    )


def _parse_msg(filename: str, data: bytes) -> str | None:
    try:
        import extract_msg  # lazy import: uploads keep working without the dependency
    except ImportError:
        return None

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        message = extract_msg.Message(tmp_path)
        try:
            subject = _one_line(message.subject)
            sender = _one_line(message.sender)
            to = _one_line(message.to)
            cc = _one_line(message.cc)
            date = _one_line(message.date)
            body = message.body or ""
            if not str(body).strip():
                html_body = getattr(message, "htmlBody", None)
                body = _strip_html(html_body) if html_body else ""
            attachment_names: list[str] = []
            for att in getattr(message, "attachments", None) or []:
                name = _one_line(getattr(att, "longFilename", "") or getattr(att, "shortFilename", ""))
                if name:
                    attachment_names.append(name)
        finally:
            try:
                message.close()
            except Exception:
                pass
    except Exception:
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return _build_markdown(
        filename,
        subject,
        sender,
        to,
        cc,
        date,
        str(body),
        _dedupe(attachment_names),
    )
