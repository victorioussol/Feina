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

8. Enable `afsa-ingresos` as well, then reconcile and read the workbook back. With that flag off the script stays silent and writes nothing:

   ```bash
   python3 /root/.hermes/scripts/afsa_reconcile.py --date yesterday \
     --membr ~/.hermes/feina-client/runs/<yesterday>/membr-pos-<yesterday>.xlsx
   ```

   The JSON must say `"confirmed_write": true`. If it does not, the run failed.

9. Only then review `CRON-COMMANDS.sh` and register the jobs you enabled. Drop Paycomet and Harlands exports in `~/.hermes/feina-client/inbox/` as `paycomet-YYYY-MM-DD.xlsx` and `harlands-YYYY-MM-DD.xlsx` when you have them. They are optional until `required: true`.

## What stays manual

- Registering cron (the shell file is a review list).
- The human Membr login, including the captcha.
- Uploading the workbook to Drive. Composio is not available to a no-agent script on v0.21.7. After the local write is confirmed, a short model turn can upload and must run `afsa_reconcile.py --verify-drive`.
- Turning on each proactive flag.
- Any message to a member or to the gestor. Those are drafts until the client says yes.

## Hermes v0.21.7 limits

- Gateway `delegate_task` returns immediately and delivers the result later. Cron and one-shot CLI sessions wait, so the night job must stay `--no-agent`.
- `delegate_task(background=true)` is ignored. Do not use it.
- Subagents cannot send Telegram or create cron jobs.
- There is no gateway-level single-flight queue. Two inbound messages can start before either takes the lock. The lock still stops two Membr downloads.
- v0.22's stuck-turn watchdog, loop guardrails, cron webhooks and Bot Screen are not required for these scripts and are not enabled here. The template pin stays v0.21.7.
- `failure_deliver` is not in the v0.21.7 cron docs we built against. Ops alerts are a Slack webhook from the script, and ops crons use `--deliver local` so a failure text cannot land in the client's Telegram.
