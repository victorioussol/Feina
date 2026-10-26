---
name: membr-login-guard
description: Check whether the Membr session will still be valid at 04:00, alert Feina on Slack once, and re-run a failed AFSA night once after a human logs in.
version: 1.1.1
metadata:
  hermes:
    tags: [Membr, Login, Slack, AFSA]
---

# Membr login guard

Off until `/root/.hermes/feina-client/enabled/membr-login-guard` exists. The re-run also needs `afsa-ingresos` enabled.

Two no-LLM checks, 20:00 and 03:30 Europe/Madrid, open the club home page in a new tab of the existing browser profile. The check reads the page. A loaded dashboard is signed in. A login form or a captcha is not. Membr keeps that login in page storage. Cookie names are not the signal. The 26 Oct 2026 run saw `__stripe_*`, `_hj*`, and `AWSALB*` only.

- A login that was just observed (a wall, then a dashboard) lasts 24 hours from that moment. A page that is merely still logged in does not extend the clock.
- At 20:00, a logged-in page with no observed login is treated as not safe for 04:00.
- At 03:30, a logged-in page is treated as safe for the 04:00 run half an hour later.

If it will not be valid, one Slack message that day goes to `FEINA_VINCE_SLACK_WEBHOOK`. The text is a status code only. It never includes member rows, amounts, conversation text, or cookies. It is never sent to the client's Telegram.

A watcher runs every 10 minutes and reads the local Chrome cookie file (name, host, creation, expiry — not the value) so it can notice a file change after a login wall. That change is not itself proof of a Membr session. The watcher does not open Membr on those ticks. If the file changes after a login wall, and the night's AFSA run failed, was skipped, or never wrote the workbook, it starts that job once. The re-run still stops when the page is a login form or a captcha. The shared lock means it waits rather than overlapping a run that is already going. Between 03:30 and 04:10 it stays out of the way so the scheduled job can start.

A human logs in on the existing browser. This skill does not type, does not solve captchas, and does not keep the session warm.
