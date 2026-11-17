"""Daily on-call reminder workflow.

Every morning the workflow reads the newest schedule picture posted in
#schedule-picture, decodes it with a vision model using the
oncall-schedule-reader legend, and DMs raptor today's and tomorrow's
on-call coverage.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import mistralai.workflows as workflows

from worker.schedule import (
    build_reminder_message,
    month_label,
    parse_decoded_schedule,
    pick_latest_schedule_image,
)

SLACK_API_BASE = "https://slack.com/api"
UPLOAD_CHANNEL_ID = "C0CJECM9BSP"
REMINDER_CHANNEL_ID = "U0CJE5P5RPD"
CLINIC_TZ = ZoneInfo("America/Chicago")
VISION_MODEL = "pixtral-large-latest"
HISTORY_LIMIT = 50

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


async def _slack_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    token = os.environ["SLACK_BOT_TOKEN"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{SLACK_API_BASE}/{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack API {path} failed: {payload.get('error')}")
    return payload


async def _slack_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    import httpx

    token = os.environ["SLACK_BOT_TOKEN"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{SLACK_API_BASE}/{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack API {path} failed: {payload.get('error')}")
    return payload


async def _download_image(url: str) -> bytes:
    import httpx

    token = os.environ["SLACK_BOT_TOKEN"]
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        return response.content


async def _decode_image(image_b64: str, month: str) -> dict[str, Any]:
    from mistralai.workflows.client import get_mistral_client

    client = get_mistral_client()
    response = await client.chat.complete_async(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": DECODE_INSTRUCTIONS.format(month_label=month)},
                    {
                        "type": "image_url",
                        "image_url": f"data:image/png;base64,{image_b64}",
                    },
                ],
            }
        ],
        temperature=0.0,
    )
    content = response.choices[0].message.content
    if isinstance(content, list):
        content = "".join(part.text for part in content)
    return parse_decoded_schedule(content or "")


@workflows.activity(start_to_close_timeout=timedelta(seconds=30), retry_policy_max_attempts=3)
async def resolve_now(run_date: str | None) -> str:
    if run_date is None:
        return datetime.now(CLINIC_TZ).isoformat()
    return datetime.fromisoformat(run_date).replace(tzinfo=CLINIC_TZ).isoformat()


@workflows.activity(start_to_close_timeout=timedelta(seconds=60), retry_policy_max_attempts=3)
async def fetch_latest_schedule_image() -> dict[str, Any] | None:
    history = await _slack_get(
        "conversations.history",
        {"channel": UPLOAD_CHANNEL_ID, "limit": HISTORY_LIMIT},
    )
    return pick_latest_schedule_image(history.get("messages") or [])


@workflows.activity(start_to_close_timeout=timedelta(seconds=120), retry_policy_max_attempts=3)
async def download_schedule_image(image_ref: dict[str, Any]) -> str:
    content = await _download_image(image_ref["url_private"])
    return base64.b64encode(content).decode("ascii")


@workflows.activity(start_to_close_timeout=timedelta(seconds=180), retry_policy_max_attempts=3)
async def decode_schedule_image(image_b64: str, month: str) -> dict[str, Any]:
    return await _decode_image(image_b64, month)


@workflows.activity(start_to_close_timeout=timedelta(seconds=60), retry_policy_max_attempts=3)
async def send_reminder(message: str) -> None:
    await _slack_post("chat.postMessage", {"channel": REMINDER_CHANNEL_ID, "text": message})


@workflows.workflow.define(
    name="oncall-daily-reminder",
    workflow_display_name="On-call Daily Reminder",
    workflow_description="Decodes the latest schedule picture from #schedule-picture and DMs raptor today's and tomorrow's on-call coverage.",
)
class OncallDailyReminderWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, run_date: str | None = None) -> str:
        image_ref = await fetch_latest_schedule_image()
        if image_ref is None:
            await send_reminder(
                "⚠️ On-call reminder: no schedule picture found in #schedule-picture. "
                "Please upload the current month's calendar image."
            )
            return "no-schedule-image"

        now = datetime.fromisoformat(await resolve_now(run_date))
        image_b64 = await download_schedule_image(image_ref)
        schedule = await decode_schedule_image(image_b64, month_label(now))
        message = build_reminder_message(schedule, now)
        await send_reminder(message)
        return "reminder-sent"
