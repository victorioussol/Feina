# Client industry skills (drop-in)

The AFSA / Membr / proactive packs in this folder ship **disabled**. Bootstrap copies the files onto a new image and does not register their cron jobs, create their enable flags, or contact a live client computer.

Turn a part on only as a separate, manually approved step on that computer:

```bash
python3 ops/install_client_parts.py --dest /root/.hermes \
  --enable membr-download --apply
```

See [docs/INSTALL-v1.1.0.md](../../docs/INSTALL-v1.1.0.md). The installer backs up any file it would overwrite and records the SHA-256. It writes `CRON-COMMANDS.sh` and does not run it.

Enable flags live at `/root/.hermes/feina-client/enabled/<part>`:

| Flag | What it turns on |
|---|---|
| `membr-download` | Playwright download of Membr's own Excel exports |
| `membr-login-guard` | 20:00 and 03:30 session check, one Slack alert, one re-run |
| `telegram-background` | Instant acknowledgement and one long job per chat |
| `proactive-starters` | The starter set. Each message type is still off in `proactive.yaml` |
| `afsa-ingresos` | Nightly workbook. The model calls the scripts instead of clicking Membr |
| `afsa-evals` | 06:00 workbook, step-budget, and session checks to Slack |

Restart the gateway after copying skill files:

```bash
feina-gateway-restart
```
