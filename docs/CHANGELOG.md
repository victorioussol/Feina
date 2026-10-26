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

The night job no longer builds its own Resumen / Descuadres / Control workbook and no longer applies a €5 pairing rule. It checks the downloaded files and stops without a final figure when the format, the parse, the date range, the on-screen total, or a source is not right. Duplicates and unclassified rows are listed and not written. The day's row is written only by the approved `update_workbook.py`, into Vince's existing AFSA Ingresos file, after a SHA-256 backup, and only that row may change. `afsa_checks.py`, `update_workbook.py`, the `membr-card-reconciliation` skill, and `references/af-ingresos-daily.md` are not in this repository. This template applies no tolerance of its own. The on-screen total must equal the file exactly. No hand-checked past day is stored here; 20 Oct 2026 as row 294 is a layout example, and the golden harness compares a day only after one is supplied.

## Template v1.0.0

Initial Feina client image. Hermes v0.21.7, Telegram, Composio, Honcho, Latitude. Industry packs were not included.
