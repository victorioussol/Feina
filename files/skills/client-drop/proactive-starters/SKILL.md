---
name: proactive-starters
description: Quiet proactive notes for a client. Every behaviour is off until its flag is turned on. External messages stay drafts.
version: 1.1.0
metadata:
  hermes:
    tags: [Proactive, Telegram, AFSA, Tax]
---

# Proactive starters

Off until `/root/.hermes/feina-client/enabled/proactive-starters` exists. Inside that, each behaviour has its own flag in `proactive.yaml`. All of them ship false.

Language comes from `client.yaml` (`language: fr` for Vince).

| Flag | What | When |
|---|---|---|
| `daily` | Workbook is ready, plus only the mismatches | 09:00 Madrid. Silent if the night did not confirm a write |
| `monday` | Notable metric changes and failed direct debits, with drafts | Mondays, inside the same 09:00 run. Silent if nothing moved and nothing failed |
| `tax` | AEAT 20 Jan/Apr/Jul/Oct, and 30 Jan annual, 10 days ahead, one follow-up | Same morning run, only on those dates |
| `month_end` | Draft email to the gestor | First weekday of the month |
| reminders | "Remind me" | `feina_reminders.py add`, delivered by the 15-minute cron |

Rules the script enforces:

- At most 2 unprompted messages a Madrid day. Requested reminders do not count toward that cap.
- Quiet hours 22:00–08:00. A requested reminder fires inside quiet hours only when the client named that time (`--allow-quiet`).
- After 3 ignored messages of one type, that type pauses and asks once. `feina_reminders.py unpause --kind <type>` turns it back on. Any client message should run `feina_reminders.py inbound` so a reply clears the counter.
- Nothing is printed when there is nothing to say. Cron delivery is Telegram, and empty stdout sends nothing.
- `external_send_allowed()` is false. Member texts and the gestor email are drafts in the Telegram note. Send them only after an explicit yes, the same rule as `SOUL.md`.

The morning script also refuses to speak when the machine clock is not within 20 minutes of 09:00 Madrid, and tells Slack `timezone_window` once. Set the computer's timezone to Europe/Madrid before registering the cron.
