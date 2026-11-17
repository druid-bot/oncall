"""Daily on-call reminder runner for GitHub Actions.

Decodes the newest schedule picture in #schedule-picture with the Mistral
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
    VISION_MODEL,
    build_reminder_message,
    month_label,
    parse_decoded_schedule,
    pick_latest_schedule_image,
)

SLACK_API_BASE = "https://slack.com/api"
MISTRAL_API_BASE = "https://api.mistral.ai/v1"
UPLOAD_CHANNEL_ID = "C0CJECM9BSP"
REMINDER_CHANNEL_ID = "U0CJE5P5RPD"
CLINIC_TZ = ZoneInfo("America/Chicago")
HISTORY_LIMIT = 50


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


def decode_image(image_b64: str, month: str) -> dict[str, Any]:
    api_key = os.environ["MISTRAL_API_KEY"]
    response = httpx.post(
        f"{MISTRAL_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": VISION_MODEL,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DECODE_INSTRUCTIONS.format(month_label=month)},
                        {"type": "image_url", "image_url": f"data:image/png;base64,{image_b64}"},
                    ],
                }
            ],
        },
        timeout=180.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content)
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
    schedule = decode_image(base64.b64encode(content).decode("ascii"), month_label(now))
    message = build_reminder_message(schedule, now)
    slack_post("chat.postMessage", {"channel": REMINDER_CHANNEL_ID, "text": message})
    print("reminder sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
