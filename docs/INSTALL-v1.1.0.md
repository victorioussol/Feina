# Installing template v1.1.0 parts

This does not deploy anything. Run it on a client computer only after that step has been approved by hand. The commands below copy files and write an enable flag. They do not register cron, and they do not open Membr.

Set the computer timezone first:

```bash
timedatectl set-timezone Europe/Madrid
```

Hermes v0.21.7 cron uses the machine clock. A job set for 09:00 on a UTC clock will fire at the wrong hour. The morning script stays silent and sends Slack `timezone_window` once if it is started outside 08:40–09:20 Madrid.

## Enable one part

From a checkout of this repo, on the client computer:

```bash
python3 ops/install_client_parts.py --dest /root/.hermes --enable membr-download --apply
```

Repeat `--enable` for each part you want: `membr-download`, `membr-login-guard`, `telegram-background`, `proactive-starters`, `afsa-ingresos`, `afsa-evals`.

The installer:

- copies scripts to `/root/.hermes/scripts/` (Hermes only runs cron scripts from there)
- copies each skill under `/root/.hermes/skills/client-drop/`
- creates `/root/.hermes/feina-client/enabled/<part>`
- copies `client.yaml`, `membr.reports.yaml` and `proactive.yaml` only if they are missing
- backs up any file it would overwrite and writes a SHA-256 next to the backup
- writes `/root/.hermes/feina-client/CRON-COMMANDS.sh` and does **not** run it

Hermes v0.21.7 `--script` is a file and does not take arguments. Jobs that need arguments (`--slot morning`, `--slot reminders`) are registered as wrapper scripts, `proactive_morning.py` and `proactive_reminders.py`.

A dry run (no `--apply`) only prints the plan.

Do not put `ORGO_API_KEY` on the client. The installer refuses to copy a file that contains one. The Slack webhook is the environment variable `FEINA_VINCE_SLACK_WEBHOOK`. It is not written into a file by this installer. Add that name to `terminal.env_passthrough` (the v1.1.0 `config.yaml` already lists it) so a no-agent cron can see it. Cron scripts do not inherit arbitrary secrets.

Restart the gateway after the copy:

```bash
supervisorctl restart hermes-gateway
```

## Client file

Edit `/root/.hermes/feina-client/client.yaml`. For Vince:

```yaml
client_slug: vince
language: fr
timezone: Europe/Madrid
slack_webhook_env: FEINA_VINCE_SLACK_WEBHOOK
```

Proactive flags stay false until you edit `proactive.yaml`.

## Supervised first run of the Membr script

Do this once, with a person watching the browser. Membr must already be logged in. Nobody types a password into the script.

1. Enable `membr-download` as above.
2. Point `browser.user_data_dir` in `membr.reports.yaml` at the same directory as `browser.user_data_dir` in `~/.hermes/config.yaml`. The profile must already exist. The script will not create an empty one.
3. Replace `REPLACE_CLUB` in `club_base_url` with the club's real host (`https://<club>.membr.com` and nothing after the host).
4. If Chrome is not already listening, start it yourself on the existing profile:

   ```bash
   google-chrome --remote-debugging-port=9222 \
     --user-data-dir=/root/.hermes/browser-profile \
     --no-first-run --no-default-browser-check
   ```

5. Dry run, landing page only:

   ```bash
   python3 /root/.hermes/scripts/membr_download.py --dry-run --date yesterday
   ```

   Expect a manifest under `~/.hermes/feina-client/runs/<yesterday>/`. If the status is `LOGIN_REQUIRED`, stop. A person logs in on that same browser. Do not rerun in a loop.

6. Inspect, which clicks the configured labels and still does not download:

   ```bash
   python3 /root/.hermes/scripts/membr_download.py --inspect --date yesterday
   ```

   Open `manifest.json`. Every step marked `guess: true` in `references/selectors.md` is unverified. Fix the labels and CSS in `membr.reports.yaml` from the recorded elements. Do not add URLs.

7. One real download, still watched:

   ```bash
   python3 /root/.hermes/scripts/membr_download.py --date yesterday
   ```

   Check the xlsx opens and the SHA-256 in the manifest matches `sha256sum` of the file.

8. From the inspect manifest, copy the real on-screen row-count and total selectors into the `read_screen` step. The download stores that text and saves the file as `runs/<date>/pos-export.xlsx`. It does not rebuild the workbook. `afsa_checks.py export` is the check: sheets `Informe` and `Informe Meta Data`, report name `Transaccion Punto de Venta`, a period that covers the whole business date, and a download time after that day ended. The on-screen text is not compared with the one-day total, because a real export may cover more than that day.

9. The installer copies the approved skill to `skills/membr-card-reconciliation/` and writes `feina-client/skill-hashes.json`. The scripts `afsa_checks.py` and `update_workbook.py` are already in the template under `skills/client-drop/afsa-ingresos/approved/`, with sha256 in `hashes.json`. Do not edit them. A hash mismatch is `CHECKS_UNAVAILABLE`. The 06:15 eval alerts Slack (`skill_hash_drift`) if the installed skill files change. It does not rewrite them.

   On Hermes v0.21.7 the automatic background review is `auxiliary.background_review.enabled` in `~/.hermes/config.yaml` (default true, and a broken config leaves it on). Set it to `false` to stop that fork from editing skills. `skills.creation_nudge_interval: 0` only stops the skill-review trigger; at this pin the memory-review fork still has the skills toolset. This installer does not change that config on a client.

10. Enable `afsa-ingresos`. The workbook must already be Vince's AFSA Ingresos file. Column H is Comentario and is never written. Harlands is not an input. The payment total comes from `daily-payload.json`; `dates` only checks the Redsys and Paycomet PDFs.

    ```bash
    python3 /root/.hermes/scripts/afsa_reconcile.py --date yesterday \
      --membr ~/.hermes/feina-client/runs/<yesterday>/pos-export.xlsx \
      --pdf ~/.hermes/feina-client/runs/<yesterday>/<redsys>.pdf \
      --pdf ~/.hermes/feina-client/runs/<yesterday>/<paycomet>.pdf \
      --evidence ~/.hermes/feina-client/runs/<yesterday>/processor-evidence.json \
      --payload ~/.hermes/feina-client/runs/<yesterday>/daily-payload.json \
      --workbook /path/to/AFSA\ Ingresos.xlsx
    ```

    `figures_final: true` only after `afsa_checks.py final` PASSes. That command reads `/root/.hermes/automation/af-ingresos/last-success.json`, which is written after the Drive read-back, not by this template. Until then the outcome is unverified and no figure is final. There is no tolerance.

11. Only then review `CRON-COMMANDS.sh` and register the jobs you enabled. The 06:00 workbook eval passes only when `final` has passed.

12. The golden day is 20 Oct 2026, sheet `2026`, row 294. Its Membr export is not in the fixture, so that test uses `daily-payload.json` and says `export` is not covered. A later export can be dropped in `tests/fixtures/golden/pending-membr-export/`.

## What stays manual

- Registering cron (the shell file is a review list).
- The human Membr login, including the captcha.
- Uploading the workbook to Drive and writing `last-success.json`. Composio is not available to a no-agent script on v0.21.7. After the original file is read back, write that JSON (business date, `report_readback_verified` true, the original Drive id, md5, timestamp) and run `afsa_checks.py final`. `afsa_reconcile.py --verify-drive` only checks the metadata dict; it does not mark the day verified.
- Turning on each proactive flag.
- Any message to a member or to the gestor. Those are drafts until the client says yes.

## Hermes v0.21.7 limits

- Gateway `delegate_task` returns immediately and delivers the result later. Cron and one-shot CLI sessions wait, so the night job must stay `--no-agent`.
- `delegate_task(background=true)` is ignored. Do not use it.
- Subagents cannot send Telegram or create cron jobs.
- There is no gateway-level single-flight queue. Two inbound messages can start before either takes the lock. The lock still stops two Membr downloads.
- v0.22's stuck-turn watchdog, loop guardrails, cron webhooks and Bot Screen are not required for these scripts and are not enabled here. The template pin stays v0.21.7.
- `failure_deliver` is not in the v0.21.7 cron docs we built against. Ops alerts are a Slack webhook from the script, and ops crons use `--deliver local` so a failure text cannot land in the client's Telegram.
