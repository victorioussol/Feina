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

The reconcile script does not invent figures and does not apply a tolerance. It stops the day, with no final number, when:

- a header is unrecognized or a required column is missing (`SOURCE_FORMAT_CHANGED`)
- a date, amount, or receipt cannot be parsed (`PARSE_FAILED`, with a count)
- the file is empty, has no rows for the day, or covers any day other than the target (`NEEDS_CONFIRMATION`)
- Membr's on-screen row count or total does not exactly equal the file (`SCREEN_MISMATCH`)
- only Membr is present (`Membr only, not cross-checked`)
- a receipt is duplicated or a row's method matches none of the known words (listed, not dropped, not written)

When those gates pass, it runs the approved `afsa_checks.py export` and `update_workbook.py` if they are installed. They are not in this template. A missing script is `CHECKS_UNAVAILABLE`. The workbook is Vince's existing `AFSA Ingresos` file. The write backs it up, replaces only the target day's row, reads that row back cell by cell, and restores the backup if any other row changes or column H is hidden.

Tell the client one of three things: verified and matching; verified but the platforms disagree (what each system shows, and what to look up); or not verified, with no figure given as final. Never adjust a platform amount.

Drive upload is not inside the no-agent job: Composio is a model tool on v0.21.7. After a confirmed local write, if the client config has a Drive file id, upload that exact file and save the metadata JSON. Then `afsa_reconcile.py --verify-drive <json> --workbook <path>`. If that check fails, the run is failed. Do not tell the client the Drive copy is updated until the read-back says so.

A `LOGIN_REQUIRED` result is the end of the run. The login guard re-runs it once after a person logs in.
