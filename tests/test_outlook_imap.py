"""Tests for Outlook IMAP link extraction."""

from email.message import EmailMessage

from job_automation.email.outlook_imap import BUILTIN_LINK_PATTERNS, _extract_links_from_message, _sender_matches


def test_extract_builtin_magic_link_from_html():
    msg = EmailMessage()
    msg["From"] = "Built In <noreply@accounts.builtin.com>"
    msg.set_content(
        '<a href="https://accounts.builtin.com/login/verify?token=abc123">Log in</a>',
        subtype="html",
    )
    links = _extract_links_from_message(msg, BUILTIN_LINK_PATTERNS)
    assert links
    assert links[0].startswith("https://accounts.builtin.com/login/verify")


def test_sender_matches_builtin():
    msg = EmailMessage()
    msg["From"] = "Built In <noreply@accounts.builtin.com>"
    assert _sender_matches(msg, ("builtin", "accounts.builtin"))
