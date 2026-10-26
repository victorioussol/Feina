# Changelog

## Template v1.1.0

AFSA reliability for the client-agent template. Nothing in this version registers cron jobs or contacts a live client computer. Each part stays off until its enable flag exists.

### Membr download

A Playwright script attaches to the browser profile that is already logged in, opens the club's normal address, and clicks Membr's own Download. Login pages and captchas stop the run with exit 10. Selectors live in a config file. `--inspect` and `--dry-run` record the page so a supervised run can correct them. There is no keepalive and no undocumented Membr endpoint.

### Login check and one re-run

No-LLM checks at 20:00 and 03:30 Madrid decide whether the session will still be valid at 04:00. One Slack alert per day, to `FEINA_VINCE_SLACK_WEBHOOK`, with a status code and no member or conversation content. A watcher notices a new login from the local cookie file and re-runs a failed night once, under the same lock as the 04:00 job.

### Telegram

Long requests get an immediate acknowledgement in the client's language, then one background `delegate_task`. A second request is queued. The background work shares the AFSA lock. Notes that need Hermes v0.22 are called out in the install guide; this template stays on v0.21.7.

### Proactive starters

Daily workbook note, Monday changes and failed-debit drafts, month-end and AEAT reminders, and "remind me". All off by default. At most two unprompted messages a day, quiet hours 22:00–08:00, pause after three ignored messages, and nothing sent when there is nothing to say. Anything that would leave the gym stays a draft.

### Evals

No-LLM checks: workbook written and read back by 06:00, under 15 model calls and 20 minutes, and a fresh Membr session. Failures go to Slack. A night with no confirmed workbook write is a failure even if Hermes cron says otherwise. An unverified night is not a success.

### Accuracy (same version)

The night job no longer builds its own workbook and no longer applies a tolerance. The production `afsa_checks.py` and `update_workbook.py`, plus the approved `membr-card-reconciliation` skill, are vendored unmodified under `files/skills/client-drop/afsa-ingresos/approved/` and checked by sha256 at runtime. A mismatch is `CHECKS_UNAVAILABLE`. The wrapper calls `export`, `dates`, `update_workbook.py SOURCE PAYLOAD OUTPUT`, `final`, and `gaps` with `--business-date`. `final` is the only step that marks a day verified. Harlands is not an input of the daily row. The Membr file is saved as `pos-export.xlsx`. The 20 Oct 2026 golden day replays `dates` and `update_workbook.py` for row 294; its Membr export is not in the fixture, so `export` is not claimed for that day. The installer copies the approved skill, records its hashes, and a 06:15 eval alerts Slack if those files drift. It does not turn background skill review off on a client.

## Template v1.0.0

Initial Feina client image. Hermes v0.21.7, Telegram, Composio, Honcho, Latitude. Industry packs were not included.
