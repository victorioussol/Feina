---
name: afsa-ingresos
description: Build the AFSA Ingresos workbook from Membr, Paycomet and Harlands files. The model calls two scripts and does not drive Membr.
version: 1.1.0
metadata:
  hermes:
    tags: [AFSA, Ingresos, Excel, Membr]
---

# AFSA Ingresos

Off until `/root/.hermes/feina-client/enabled/afsa-ingresos` exists.

The 04:00 Europe/Madrid job is `afsa_nightly.py`. It is a no-agent cron (`deliver: local`). It downloads, reconciles, writes the workbook, and reads the workbook back. `model_calls` on that path is 0. If `confirmed_write` is not true, the night is failed whatever Hermes later says about the cron.

When the client asks for the same work in chat, stay under 15 model calls:

1. Acknowledge with `feina_telegram_turn.py` if telegram-background is enabled, then delegate, or otherwise run the two commands below yourself and stop.
2. `membr_download.py --date yesterday` once.
3. `afsa_reconcile.py --date yesterday --membr <manifest path>` once. Add `--paycomet` and `--harlands` when those inbox files exist (`inbox/paycomet-YYYY-MM-DD.xlsx`, `inbox/harlands-YYYY-MM-DD.xlsx`).
4. Read the one-line JSON. Do not open the spreadsheets in the chat. Do not click Membr.

Checks the reconcile script already runs:

- Card and refund rows against Paycomet. Amounts within 5 EUR can pair. A larger gap, or an unpaired row, is a mismatch.
- Direct debits against Harlands. A failed collection is listed even when the amount matches.
- Missing Paycomet or Harlands files are mismatches only when that source is `required: true` in the Membr config. Both ship optional until the inbox files are real.

The workbook is `workbooks/AFSA-Ingresos.xlsx` with sheets Resumen, Descuadres and Control. Success means the Resumen row for the business date (yesterday in Madrid) reads back with the same totals.

Drive upload is not inside the no-agent job: Composio is a model tool on v0.21.7. After a confirmed local write, if the client config has a Drive file id, upload that exact file and save the metadata JSON. Then `afsa_reconcile.py --verify-drive <json> --workbook <path>`. If that check fails, the run is failed. Do not tell the client the Drive copy is updated until the read-back says so.

A `LOGIN_REQUIRED` result is the end of the run. The login guard re-runs it once after a person logs in.
