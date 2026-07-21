"""Tests for Built In relative posted/reposted date parsing."""

from datetime import datetime

from job_automation.etl.posted_parser import format_posted_relative, parse_posted_relative


NOW = datetime(2026, 7, 19, 22, 0)


def test_parse_five_days_ago():
    result = parse_posted_relative("5 Days Ago", now=NOW)
    assert result.posted_at == datetime(2026, 7, 14, 22, 0)
    assert result.is_reposted is False


def test_parse_reposted_hours_ago():
    result = parse_posted_relative("Reposted 5 Hours Ago", now=NOW)
    assert result.posted_at == datetime(2026, 7, 19, 17, 0)
    assert result.is_reposted is True


def test_parse_posted_prefix():
    result = parse_posted_relative("Posted 9 Hours Ago", now=NOW)
    assert result.posted_at == datetime(2026, 7, 19, 13, 0)
    assert result.is_reposted is False


def test_parse_yesterday():
    result = parse_posted_relative("Yesterday", now=NOW)
    assert result.posted_at == datetime(2026, 7, 18, 22, 0)


def test_format_reposted_relative():
    label = format_posted_relative(datetime(2026, 7, 14, 22, 0), is_reposted=True, now=NOW)
    assert label == "Reposted 5 Days Ago"


def test_format_posted_relative():
    label = format_posted_relative(datetime(2026, 7, 19, 19, 0), is_reposted=False, now=NOW)
    assert label == "Posted 3 Hours Ago"
