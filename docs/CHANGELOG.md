# Changelog

## Unreleased — FEI-42

Gateway restarts now use a guarded operator helper: direct Hermes supervision,
nonblocking lock, quiet idle/drain check, TERM-first orphan recovery and a verified
single replacement PID. Bootstrap hardens supervisor process-group shutdown.
Repo-only; no client rollout or approved reconciliation script change.

## Template v1.1.1

Membr download follows the flow checked on one supervised run on 26 Oct 2026.

The club admin sidebar `Informes` opens a submenu. Its child `Informes` opens Membr Insights in a new tab on `insights.eu.membr.com`. The script allow-lists that host plus the club host, opens its own tab, follows the new Insights tab, and closes only the tabs it opened. A tab that was already open, such as Harlands, is left alone. `--inspect` waits for the page and for network idle, then records visible menu texts, inputs, and buttons.

The report path is My Reports, Transaction Reports, POS Transactions. Dates are plain `YYYY-MM-DD` fills of `input[name='from']` and `input[name='until']`. `Select Gyms` starts with two gyms selected. The config names `Anytime Fitness Sant Adrià`. The script leaves only that gym selected and reads the screen back before Run Report. If it cannot confirm that, the status is `GYM_FILTER_UNVERIFIED`.

Run Report shows `<b>N</b> total rows` and no money total. Download Report opens a menu; the script clicks Download Report (.xlsx) and stores Membr's bytes as `runs/<date>/pos-export.xlsx` with a sha256. `N` is stored on the manifest. A different data-row count on sheet `Report` is `SCREEN_MISMATCH`. Zero rows on screen and in the file is `EMPTY_DAY_NEEDS_CONFIRMATION`. `Oops, an error has occurred` beside zero rows is a failed run.

The manifest field `date_filter_timezone` is `unverified`. The export's download-time metadata is UTC. Which clock the From/Until filter uses is still a TODO.

Membr keeps the login in page storage. The session check is the dashboard versus the login form or a captcha. The guessed cookie-name list is gone. A supervised run saw `__stripe_*`, `_hj*`, and `AWSALB*` only.

The Insights workbook uses sheets `Report` and `Report Meta Data` and report name `POS Transaction`. The vendored `afsa_checks.py` still requires `Informe`, `Informe Meta Data`, and `Transaccion Punto de Venta`. The on-screen gym is `Anytime Fitness Sant Adrià`; the checker constant is `Anytime Fitness Sant Adria`. That approved file is unchanged. A download status of OK does not mean `afsa_checks.py export` will pass.

`afsa_checks.py dates` does not read the wall clock. It fails a PDF as `unreadable (ModuleNotFoundError)` when `pypdf` is missing, which is how the 20 Oct golden tests failed on 26 Oct in an environment without that package. With `pypdf`, those slips match 20 Oct. The same check rejects a PDF that is byte-identical to one already stored under a different date in `/root/.hermes/automation/af-ingresos/runs` when that date is listed in `verified-dates.json`. The tests send that directory to a temp folder from outside the script. `datetime.now` cannot be patched from outside, and the script has no clock env var. The export "downloaded before the business date ended" rule compares `Fecha descargado` inside the workbook with the day after the business date.

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
