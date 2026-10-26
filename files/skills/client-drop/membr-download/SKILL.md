---
name: membr-download
description: Download Membr Excel reports by clicking the club's own screens in the already logged-in browser. Never logs in.
version: 1.1.1
metadata:
  hermes:
    tags: [Membr, AFSA, Reports, Browser]
---

# Membr download

Use this only when `/root/.hermes/feina-client/enabled/membr-download` exists.

Membr is read-only. Open the club's normal web address, set the date, and click Membr's own Download. One script call. Then stop touching the browser.

```text
python3 /root/.hermes/scripts/membr_download.py --date yesterday
```

- Exit 0 and status `OK`: the xlsx bytes are Membr's, the on-screen row count matches the file, and the gym on screen is the configured gym. Hand the manifest path to `afsa_reconcile.py`. `afsa_checks.py export` still expects the Spanish workbook names, so a download OK is not an export PASS.
- Exit 10 or status `LOGIN_REQUIRED`: stop. A person has to log in. Do not retry, do not type, do not open a different URL.
- Exit 2 with `GYM_FILTER_UNVERIFIED`, `SCREEN_MISMATCH`, `EMPTY_DAY_NEEDS_CONFIRMATION`, or `FAILED`: stop. Do not treat the day as a success. An empty day is not a success.
- `--inspect` or `--dry-run`: wait for the page, record menus, inputs, and buttons under `runs/<date>/`, and do not download.

## Hard rules

- Never type a password, a username, or a one-time code.
- Never click a captcha or a login button.
- Never call `browser_vault_save_login`.
- Open the club home page, then only hosts in `allowed_hosts` (`insights.eu.membr.com` on the checked club). No other host, no undocumented endpoint, no keepalive.
- Open a new tab. Follow the Insights tab that the Informes submenu opens. Close only tabs this run opened. Leave every pre-existing tab alone.
- Session state is the page (dashboard, login form, or captcha). Cookie names are not a login signal. Cookie values are never read.

## Selectors

`membr.reports.yaml` holds the labels checked on 26 Oct 2026. The path is Informes (submenu, new Insights tab), My Reports, Transaction Reports, POS Transactions. Dates are `input[name='from']` and `input[name='until']`, filled as `YYYY-MM-DD`. The gym is `Anytime Fitness Sant Adrià`. Run Report, then Download Report (.xlsx). The on-screen count is `<b>N</b> total rows`.

`date_filter_timezone` in the manifest stays `unverified`. The export download-time metadata is UTC. Which clock the date filter uses is still open.

The live export sheets are `Report` and `Report Meta Data`, report name `POS Transaction`. `files/skills/client-drop/afsa-ingresos/approved/afsa_checks.py` still accepts only `Informe` / `Informe Meta Data` / `Transaccion Punto de Venta`. Do not edit that file.

`member_payments` and `direct_debits` stay disabled.

See `references/selectors.md`.
