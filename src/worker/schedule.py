"""Pure helpers to pick, decode, and format the on-call schedule.

These functions have no network or model access so they can be tested
deterministically; the workflow activities wrap them with I/O.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

VISION_MODEL = "pixtral-large-latest"

DECODE_INSTRUCTIONS = """You are decoding a scanned monthly on-call calendar for a clinic.
The calendar month is {month_label}.

Legend:
- Circled or parenthesized initials, e.g. (A): that person is on clinic call 8am-5pm that day.
- Initials with dashes, e.g. -T-: that person is off / on vacation that day.
- SC-XX entries, e.g. SC-BKN: shared call. A day may have several.
- Saturdays: the circled person is on call 8am-5pm.
- Plain (uncircled, undashed) initials are regular schedule entries; list them under "regular".
- Cell notes such as "Clinic Closed Thanksgiving" or "Daylight Snow" go in "notes".
- An empty cell means no special coverage is listed.

Output STRICT JSON only, with no markdown fences and no commentary:
{{"month": "YYYY-MM", "days": {{"<day-of-month>": {{"clinic_call": "", "shared_call": [], "off": [], "regular": [], "notes": "", "unreadable": false}}}}}}

Rules:
- Use initials exactly as written; never invent people or coverage.
- Use "" / [] when a field is absent.
- Set "unreadable": true when a cell cannot be read confidently.
- Include every day of the month shown on the calendar."""


def pick_latest_schedule_image(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a reference to the newest image file posted in the channel.

    ``messages`` is a Slack ``conversations.history`` payload (newest first).
    """
    for message in messages:
        for file in message.get("files") or []:
            mimetype = file.get("mimetype", "")
            url = file.get("url_private") or file.get("url_private_download")
            if mimetype.startswith("image/") and url:
                return {
                    "file_id": file.get("id"),
                    "url_private": url,
                    "message_ts": message.get("ts"),
                    "mimetype": mimetype,
                }
    return None


def parse_decoded_schedule(text: str) -> dict[str, Any]:
    """Parse the vision model output into a validated schedule dict."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model output contains no JSON object")
    decoded = json.loads(cleaned[start : end + 1])
    month = decoded.get("month")
    days = decoded.get("days")
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError(f"invalid month in decoded schedule: {month!r}")
    if not isinstance(days, dict):
        raise ValueError("decoded schedule has no days mapping")
    return decoded


def day_summary(schedule: dict[str, Any], day: date) -> dict[str, Any]:
    """Return the decoded entry for one date, or an empty summary."""
    days = schedule.get("days") or {}
    entry = days.get(str(day.day)) or {}
    return {
        "clinic_call": entry.get("clinic_call") or "",
        "shared_call": entry.get("shared_call") or [],
        "off": entry.get("off") or [],
        "regular": entry.get("regular") or [],
        "notes": entry.get("notes") or "",
        "unreadable": bool(entry.get("unreadable")),
    }


def _join(items: list[str]) -> str:
    return ", ".join(items)


def format_day_block(summary: dict[str, Any], day: date) -> str:
    """Format one day per the oncall-schedule-reader reminder template."""
    label = f"{WEEKDAY_NAMES[day.weekday()]} {day.strftime('%B')} {day.day}"
    lines = [f"📅 On-call for {label}:"]

    if summary["unreadable"]:
        lines.append("• Schedule cell unreadable in the scan — please check the picture")
        return "\n".join(lines)

    notes = summary["notes"]
    if notes and "closed" in notes.lower():
        lines.append(f"• Clinic closed — {notes}")
        return "\n".join(lines)

    clinic_call = summary["clinic_call"]
    if clinic_call:
        lines.append(f"• Clinic call 8am–5pm: {clinic_call}")
    elif day.weekday() == 5:
        lines.append("• No circled person listed for Saturday")
    else:
        lines.append("• No clinic call listed")

    if summary["shared_call"]:
        lines.append(f"• Shared call: {_join(summary['shared_call'])}")
    if summary["off"]:
        lines.append(f"• Off: {_join(summary['off'])}")
    if notes:
        lines.append(f"• Notes: {notes}")
    return "\n".join(lines)


def build_reminder_message(schedule: dict[str, Any], now: datetime) -> str:
    """Build the daily reminder covering today and tomorrow."""
    today = now.date()
    blocks = [
        format_day_block(day_summary(schedule, today), today),
        format_day_block(day_summary(schedule, today + timedelta(days=1)), today + timedelta(days=1)),
    ]
    return "\n\n".join(blocks)


def month_label(now: datetime) -> str:
    """Human label of the month whose schedule is expected, e.g. 'December 2026'."""
    return now.strftime("%B %Y")
