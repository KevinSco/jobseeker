"""Tests for portal login configuration."""

from job_automation.browser.portal_login import PORTAL_LOGIN_CONFIG, normalize_login_url


def test_builtin_magic_link_config():
    config = PORTAL_LOGIN_CONFIG["builtin"]
    assert config.magic_link is True
    assert config.password_selectors == []
    assert config.email_type_delay_ms == 200
    assert "input[data-js='email']" in config.email_selectors
    assert "button.submit.email.button" in config.submit_selectors


def test_builtin_homepage_login_url_ignored():
    assert normalize_login_url("builtin", "https://builtin.com/") is None
