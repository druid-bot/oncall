"""Unit tests for the pure schedule helpers."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from worker.schedule import (
    build_reminder_message,
    day_summary,
    format_day_block,
    parse_decoded_schedule,
    pick_latest_schedule_image,
)


def test_pick_latest_schedule_image_prefers_newest_image():
    messages = [
        {"ts": "1731900000.000100", "text": "no files here"},
        {
            "ts": "1731900000.000300",
            "files": [
                {"id": "F2", "mimetype": "image/jpeg", "url_private": "https://files.slack.com/F2"},
            ],
        },
        {
            "ts": "1731900000.000200",
            "files": [
                {"id": "F1", "mimetype": "image/png", "url_private": "https://files.slack.com/F1"},
                {"id": "F3", "mimetype": "application/pdf", "url_private": "https://files.slack.com/F3"},
            ],
        },
    ]

    ref = pick_latest_schedule_image(messages)

    assert ref == {
        "file_id": "F2",
        "url_private": "https://files.slack.com/F2",
        "message_ts": "1731900000.000300",
        "mimetype": "image/jpeg",
    }


def test_pick_latest_schedule_image_returns_none_without_images():
    messages = [
        {"ts": "1", "files": [{"id": "F", "mimetype": "application/pdf", "url_private": "u"}]},
        {"ts": "2", "text": "plain"},
    ]
    assert pick_latest_schedule_image(messages) is None


def test_parse_decoded_schedule_strips_code_fence():
    text = '```json\n{"month": "2026-12", "days": {"1": {"clinic_call": "A"}}}\n```'
    decoded = parse_decoded_schedule(text)
    assert decoded["month"] == "2026-12"
    assert decoded["days"]["1"]["clinic_call"] == "A"


def test_parse_decoded_schedule_rejects_missing_month():
    with pytest.raises(ValueError):
        parse_decoded_schedule('{"days": {}}')


def test_day_summary_defaults_missing_fields():
    schedule = {"month": "2026-12", "days": {"2": {"clinic_call": "A", "off": ["T"]}}}
    summary = day_summary(schedule, datetime(2026, 12, 2).date())
    assert summary["clinic_call"] == "A"
    assert summary["off"] == ["T"]
    assert summary["shared_call"] == []
    assert summary["unreadable"] is False


def test_format_day_block_clinic_call_and_shared():
    day = datetime(2026, 12, 12).date()
    block = format_day_block(
        {"clinic_call": "A", "shared_call": ["SC-AR"], "off": [], "regular": ["T"], "notes": "", "unreadable": False},
        day,
    )
    assert block == (
        "📅 On-call for Saturday December 12:\n"
        "• Clinic call 8am–5pm: A\n"
        "• Shared call: SC-AR"
    )


def test_format_day_block_clinic_closed():
    day = datetime(2026, 11, 26).date()
    block = format_day_block(
        {"clinic_call": "", "shared_call": [], "off": [], "regular": [], "notes": "Clinic Closed Thanksgiving", "unreadable": False},
        day,
    )
    assert block == "📅 On-call for Thursday November 26:\n• Clinic closed — Clinic Closed Thanksgiving"


def test_format_day_block_unreadable():
    day = datetime(2026, 12, 3).date()
    block = format_day_block(
        {"clinic_call": "", "shared_call": [], "off": [], "regular": [], "notes": "", "unreadable": True},
        day,
    )
    assert "unreadable" in block


def test_build_reminder_message_covers_today_and_tomorrow():
    schedule = {
        "month": "2026-11",
        "days": {
            "12": {"clinic_call": "A", "shared_call": ["SC-AR"], "off": [], "regular": ["T"], "notes": "", "unreadable": False},
            "13": {"clinic_call": "T", "shared_call": [], "off": [], "regular": ["B", "A"], "notes": "", "unreadable": False},
        },
    }
    now = datetime(2026, 11, 12, 8, 0, tzinfo=ZoneInfo("America/Chicago"))
    message = build_reminder_message(schedule, now)
    assert "On-call for Thursday November 12:" in message
    assert "Clinic call 8am–5pm: A" in message
    assert "Shared call: SC-AR" in message
    assert "On-call for Friday November 13:" in message
    assert "Clinic call 8am–5pm: T" in message
