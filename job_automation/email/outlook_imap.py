"""Fetch magic-link verification URLs from Outlook via IMAP."""

from __future__ import annotations

import email
import imaplib
import re
import time
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime

OUTLOOK_IMAP_HOST = "outlook.office365.com"
OUTLOOK_IMAP_PORT = 993

BUILTIN_LINK_PATTERNS = [
    re.compile(r"https://accounts\.builtin\.com[^\s\"'<>]+", re.I),
    re.compile(r"https://[^\s\"'<>]*builtin\.com[^\s\"'<>]*", re.I),
]

BUILTIN_SENDER_KEYWORDS = ("builtin", "accounts.builtin")


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    decoded: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _message_datetime(msg: Message):
    try:
        date_header = msg.get("Date")
        if date_header:
            return parsedate_to_datetime(date_header)
    except Exception:
        pass
    return None


def _extract_links_from_message(msg: Message, patterns: list[re.Pattern[str]]) -> list[str]:
    bodies: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        bodies.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                bodies.append(payload.decode(msg.get_content_charset() or "utf-8", errors="replace"))
        except Exception:
            pass

    links: list[str] = []
    for body in bodies:
        for pattern in patterns:
            links.extend(pattern.findall(body))
    # Prefer accounts.builtin.com login links; drop tracking pixels / images.
    cleaned = []
    for link in links:
        link = link.rstrip(").,;]")
        if "accounts.builtin.com" in link.lower() and "unsubscribe" not in link.lower():
            cleaned.append(link)
    if cleaned:
        return cleaned
    return [link.rstrip(").,;]") for link in links if "builtin.com" in link.lower()]


def _sender_matches(msg: Message, keywords: tuple[str, ...]) -> bool:
    sender = _decode_header_value(msg.get("From")).lower()
    return any(keyword in sender for keyword in keywords)


def fetch_verification_link(
    email_address: str,
    app_password: str,
    *,
    link_patterns: list[re.Pattern[str]] | None = None,
    sender_keywords: tuple[str, ...] = BUILTIN_SENDER_KEYWORDS,
    timeout_seconds: int = 180,
    poll_interval: int = 10,
) -> str | None:
    """
    Poll Outlook inbox for a recent magic-link email and return the first matching URL.

    Requires IMAP enabled on the Outlook account and a Microsoft App Password
  (not your regular password if MFA is on).
    """
    patterns = link_patterns or BUILTIN_LINK_PATTERNS
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            link = _search_inbox_once(email_address, app_password, patterns, sender_keywords)
            if link:
                return link
        except imaplib.IMAP4.error as exc:
            # Authentication failures won't recover by retrying (e.g. Microsoft
            # deprecated IMAP basic auth for personal Outlook.com accounts).
            raise RuntimeError(
                "IMAP authentication failed. Personal Outlook.com accounts no longer "
                "support app-password (basic auth) IMAP access. Use manual link click "
                "or a provider that supports IMAP app passwords."
            ) from exc
        except Exception as exc:
            last_error = exc
        time.sleep(poll_interval)

    if last_error:
        raise RuntimeError(f"Could not fetch verification email: {last_error}") from last_error
    return None


def _search_inbox_once(
    email_address: str,
    app_password: str,
    patterns: list[re.Pattern[str]],
    sender_keywords: tuple[str, ...],
) -> str | None:
    mail = imaplib.IMAP4_SSL(OUTLOOK_IMAP_HOST, OUTLOOK_IMAP_PORT)
    try:
        mail.login(email_address, app_password)
        mail.select("INBOX")
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            status, data = mail.search(None, "ALL")
        if status != "OK" or not data or not data[0]:
            return None

        ids = data[0].split()
        for msg_id in reversed(ids[-20:]):
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            if not _sender_matches(msg, sender_keywords):
                continue
            links = _extract_links_from_message(msg, patterns)
            if links:
                return links[0]
        return None
    finally:
        try:
            mail.logout()
        except Exception:
            pass
