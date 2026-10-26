---
name: membr-download
description: Download Membr Excel reports by clicking the club's own screens in the already logged-in browser. Never logs in.
version: 1.1.0
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

- Exit 0 and status `OK`: parse nothing yourself. Hand the manifest paths to `afsa_reconcile.py`.
- Exit 10 or status `LOGIN_REQUIRED`: stop. A person has to log in. Do not retry, do not type, do not open a different URL.
- `--inspect` or `--dry-run`: record the page structure under `runs/<date>/` and do not download. This is the supervised pass that fixes selectors.

## Hard rules

- Never type a password, a username, or a one-time code.
- Never click a captcha or a login button.
- Never call `browser_vault_save_login`.
- Never request a Membr URL other than the configured club home page. No undocumented endpoints, no keepalives.
- Cookie values are not read or saved. Inspect output keeps names and expiries only.

## Selectors

`membr.reports.yaml` holds every label and CSS selector. Anything marked `guess: true` is unverified. The public manuals only confirm the navigation in words: Reports, then Membr Report, then My Reports / My Data, a Run Report button, and a Download button that exports the whole report to Excel. The POS English name is "POS Transactions Report". The Spanish name "Transacción Punto de Venta" comes from the AFSA job, not from a live look at the club.

`member_payments` and `direct_debits` are disabled until the inspect run shows they exist.

See `references/selectors.md`.
