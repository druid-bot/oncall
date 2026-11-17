"""End-to-end workflow tests with Slack and the vision model mocked out."""

import pytest
from mistralai.workflows.testing import create_test_worker

import worker.workflows.oncall as oncall

ACTIVITIES = [
    oncall.resolve_now,
    oncall.fetch_latest_schedule_image,
    oncall.download_schedule_image,
    oncall.decode_schedule_image,
    oncall.send_reminder,
]


@pytest.fixture
def slack_mocks(monkeypatch):
    posted = []

    async def fake_slack_get(path, params):
        assert path == "conversations.history"
        return {
            "ok": True,
            "messages": [
                {
                    "ts": "1731900000.000100",
                    "files": [
                        {
                            "id": "F1",
                            "mimetype": "image/png",
                            "url_private": "https://files.slack.com/files-pri/F1/december.png",
                        }
                    ],
                }
            ],
        }

    async def fake_slack_post(path, body):
        posted.append((path, body))
        return {"ok": True}

    async def fake_download(url):
        assert url.endswith("december.png")
        return b"fake-png-bytes"

    async def fake_decode(image_b64, month):
        assert image_b64 == "ZmFrZS1wbmctYnl0ZXM="
        assert month == "December 2026"
        return {
            "month": "2026-12",
            "days": {
                "2": {"clinic_call": "A", "shared_call": [], "off": ["T"], "regular": ["B"], "notes": "", "unreadable": False},
                "3": {"clinic_call": "B", "shared_call": ["SC-BKN"], "off": [], "regular": ["A"], "notes": "", "unreadable": False},
            },
        }

    monkeypatch.setattr(oncall, "_slack_get", fake_slack_get)
    monkeypatch.setattr(oncall, "_slack_post", fake_slack_post)
    monkeypatch.setattr(oncall, "_download_image", fake_download)
    monkeypatch.setattr(oncall, "_decode_image", fake_decode)
    return posted


async def _run_workflow(temporal_env, input_data: dict) -> str:
    async with create_test_worker(
        temporal_env, [oncall.OncallDailyReminderWorkflow], activities=ACTIVITIES
    ):
        handle = await temporal_env.client.start_workflow(
            "oncall-daily-reminder",
            input_data,
            id="test-oncall-reminder",
            task_queue="test-task-queue",
        )
        return (await handle.result())["result"]


async def test_workflow_sends_reminder(temporal_env, slack_mocks):
    result = await _run_workflow(temporal_env, {"run_date": "2026-12-02T08:00:00"})

    assert result == "reminder-sent"
    assert len(slack_mocks) == 1
    path, body = slack_mocks[0]
    assert path == "chat.postMessage"
    assert body["channel"] == oncall.REMINDER_CHANNEL_ID
    assert "On-call for Wednesday December 2:" in body["text"]
    assert "Clinic call 8am–5pm: A" in body["text"]
    assert "Off: T" in body["text"]
    assert "On-call for Thursday December 3:" in body["text"]
    assert "Shared call: SC-BKN" in body["text"]


async def test_workflow_reports_missing_schedule(temporal_env, monkeypatch):
    posted = []

    async def fake_slack_get(path, params):
        return {"ok": True, "messages": [{"ts": "1", "text": "no image"}]}

    async def fake_slack_post(path, body):
        posted.append(body)
        return {"ok": True}

    monkeypatch.setattr(oncall, "_slack_get", fake_slack_get)
    monkeypatch.setattr(oncall, "_slack_post", fake_slack_post)

    result = await _run_workflow(temporal_env, {})

    assert result == "no-schedule-image"
    assert "no schedule picture found" in posted[0]["text"]
