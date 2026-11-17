# oncall

Daily clinic on-call reminders, decoded from a schedule picture posted to Slack.

## How it works

1. Upload the month's scanned on-call calendar picture to the `#schedule-picture` Slack channel.
2. The `oncall-daily-reminder` workflow runs every day at 8:00 AM `America/Chicago`.
3. Each run reads the newest image in `#schedule-picture`, decodes it with a vision model using the [oncall-schedule-reader](https://github.com/druid-bot/oncall) legend, and DMs raptor today's and tomorrow's coverage.

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
| Slack credential | workspace secret `SLACK_BOT_TOKEN`, bound to env `SLACK_BOT_TOKEN` |

The Slack bot token needs `channels:history`, `files:read`, `im:write` (or `chat:write`), and `chat:write` scopes.

## Layout

- `src/worker/workflows/oncall.py` — workflow and activities
- `src/worker/schedule.py` — pure decode/format helpers
- `src/worker/entrypoints/worker.py` — worker entrypoint
- `deploy/docker/Dockerfile.worker` — managed deployment image
- `tests/` — unit and workflow tests

## Development

```bash
uv sync
uv run pytest
```

## Deployment

Managed deployment name: `oncall-worker`. Deploys build from this repository with
`dockerfile_path=deploy/docker/Dockerfile.worker`.
