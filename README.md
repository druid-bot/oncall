# oncall

Daily clinic on-call reminders, decoded from a schedule picture posted to Slack.

## How it works

1. Upload the month's scanned on-call calendar picture to the `#schedule-picture` Slack channel.
2. A GitHub Actions cron job (`.github/workflows/oncall-reminder.yml`) runs at 8:00 AM `America/Chicago` every day.
3. Each run reads the newest image in `#schedule-picture`, decodes it with the Gemini vision API using the oncall-schedule-reader legend, and DMs raptor today's and tomorrow's coverage.

Decoding legend (from the oncall-schedule-reader skill):

- Circled initials — clinic call 8am–5pm
- Dashed initials (`-T-`) — off / vacation
- `SC-XX` — shared call
- Saturdays — the circled person is on call 8am–5pm

## Configuration

| Setting | Value |
| --- | --- |
| Upload channel | `#schedule-picture` (`C0CJECM9BSP`) |
| Reminder recipient | raptor DM (`U0CJE5P5RPD`) |
| Reminder time | 08:00 daily, `America/Chicago` |
| Slack credential | GitHub secret `SLACK_BOT_TOKEN` (scopes: `channels:history`, `files:read`, `chat:write`, `im:write`) |
| Vision decode | GitHub secret `GEMINI_API_KEY` (free key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)); model defaults to `gemini-2.5-flash`, override with the `GEMINI_MODEL` env var |

## Layout

- `.github/workflows/oncall-reminder.yml` — daily 8 AM Central cron (with DST gate) and manual `workflow_dispatch`
- `scripts/daily_reminder.py` — standalone runner used by Actions
- `src/worker/workflows/oncall.py` — Mistral Workflow definition (optional managed-deployment path)
- `src/worker/schedule.py` — pure decode/format helpers shared by both runners
- `tests/` — unit and workflow tests

## Development

```bash
uv sync
uv run pytest
```

## Running it by hand

```bash
export SLACK_BOT_TOKEN=xoxb-...
export GEMINI_API_KEY=...
python scripts/daily_reminder.py
```

To test the automation immediately, run the `oncall-daily-reminder` workflow from the repository's **Actions** tab (`Run workflow`).

## Deployment

No Mistral managed deployment is required: GitHub Actions hosts the schedule. The repository also
contains a worker image (`deploy/docker/Dockerfile.worker`) if you later want to serve the
`oncall-daily-reminder` Mistral Workflow from a managed or self-hosted deployment.
