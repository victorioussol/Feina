---
name: afsa-evals
description: No-LLM checks that the AFSA workbook was written, the step budget held, and the Membr session was fresh. Alerts go to Slack.
version: 1.1.0
metadata:
  hermes:
    tags: [AFSA, Evals, Slack]
---

# AFSA evals

Off until `/root/.hermes/feina-client/enabled/afsa-evals` exists. These scripts do not call a model. They trust the night status file and the workbook, not Hermes cron's own OK.

| Check | Pass | Slack code when it fails |
|---|---|---|
| Workbook, 06:00 Madrid | Today's night has `confirmed_write`, a final verified outcome, and the target day's cells read back. Column H is not hidden | `workbook_missing`, `not_confirmed`, `stale_mtime`, `readback_mismatch` |
| Step budget, 06:05 | `model_calls` under 15 and `duration_sec` under 20 minutes | `step_budget`, `duration`, `no_run_record` |
| Session freshness | The 20:00 and 03:30 login check already decided this. The 06:10 script only re-reads that result and does not open Membr | `session_stale` if the check never ran. A login failure uses the one-a-day login alert |

Alerts use `FEINA_VINCE_SLACK_WEBHOOK` and the fixed `[feina] <code>` template. No member data, no amounts, no conversation text.

The session check and the login guard share that one login alert per Madrid day, so a bad session does not page Slack twice.
