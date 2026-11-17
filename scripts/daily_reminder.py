"""Daily on-call reminder runner for GitHub Actions.

Decodes the newest schedule picture in #schedule-picture with the Gemini
vision API and DMs raptor today's and tomorrow's coverage. Reuses the pure
logic in worker/schedule.py; only I/O lives here.
"""

from __future__ import annotations

import base64
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker.schedule import (  # noqa: E402
    DECODE_INSTRUCTIONS,
    build_reminder_message,
    month_label,
    parse_decoded_schedule,
    pick_latest_schedule_image,
)

SLACK_API_BASE = "https://slack.com/api"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
UPLOAD_CHANNEL_ID = "C0CJECM9BSP"
REMINDER_CHANNEL_ID = "U0CJE5P5RPD"
CLINIC_TZ = ZoneInfo("America/Chicago")
HISTORY_LIMIT = 50
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _slack_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}


def slack_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    response = httpx.get(
        f"{SLACK_API_BASE}/{path}",
        headers=_slack_headers(),
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack API {path} failed: {payload.get('error')}")
    return payload


def slack_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{SLACK_API_BASE}/{path}",
        headers=_slack_headers(),
        json=body,
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Slack API {path} failed: {payload.get('error')}")
    return payload


def download_image(url: str) -> bytes:
    response = httpx.get(
        url,
        headers=_slack_headers(),
        timeout=60.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def decode_image(image_bytes: bytes, mime_type: str, month: str) -> dict[str, Any]:
    response = httpx.post(
        f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "contents": [
                {
                    "parts": [
                        {"text": DECODE_INSTRUCTIONS.format(month_label=month)},
                        {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.0},
        },
        timeout=180.0,
    )
    response.raise_for_status()
    parts = response.json()["candidates"][0]["content"]["parts"]
    content = "".join(part.get("text", "") for part in parts)
    return parse_decoded_schedule(content or "")


def main() -> int:
    now = datetime.now(CLINIC_TZ)
    history = slack_get(
        "conversations.history",
        {"channel": UPLOAD_CHANNEL_ID, "limit": HISTORY_LIMIT},
    )
    image_ref = pick_latest_schedule_image(history.get("messages") or [])
    if image_ref is None:
        slack_post(
            "chat.postMessage",
            {
                "channel": REMINDER_CHANNEL_ID,
                "text": (
                    "⚠️ On-call reminder: no schedule picture found in #schedule-picture. "
                    "Please upload the current month's calendar image."
                ),
            },
        )
        print("no schedule image found")
        return 0

    content = download_image(image_ref["url_private"])
    schedule = decode_image(content, image_ref.get("mimetype", "image/png"), month_label(now))
    message = build_reminder_message(schedule, now)
    slack_post("chat.postMessage", {"channel": REMINDER_CHANNEL_ID, "text": message})
    print("reminder sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
