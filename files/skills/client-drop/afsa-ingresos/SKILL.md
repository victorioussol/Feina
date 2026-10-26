---
name: afsa-ingresos
description: Stage Vince's AFSA Ingresos row from the Membr POS export and the Paycomet and Redsys PDFs. The model calls the approved scripts and does not drive Membr.
version: 1.1.0
metadata:
  hermes:
    tags: [AFSA, Ingresos, Excel, Membr]
---

# AFSA Ingresos

Off until `/root/.hermes/feina-client/enabled/afsa-ingresos` exists.

The daily row is column B date, C Ingreso Total Membr, D Tarjeta (`=C-E`), E efectivo/bizum, F Banco (Redsys + Paycomet), G Dif banco/tarjeta (`=F-D`), H Comentario. Column H is never written. Harlands is not an input of this row. Failed direct debits stay on the weekly proactive note, which is off by default.

The 04:00 Europe/Madrid job is `afsa_nightly.py` (no-agent, `model_calls` 0). It downloads, then runs the approved scripts. A day is verified only when `afsa_checks.py final` returns PASS. Until then `figures_final` is false and no figure is quoted as final.

When the client asks for the same work in chat, stay under 15 model calls:

1. Acknowledge with `feina_telegram_turn.py` if telegram-background is enabled, then delegate, or otherwise run the two commands below yourself and stop.
2. `membr_download.py --date yesterday` once. The file is `runs/<date>/pos-export.xlsx`.
3. `afsa_reconcile.py --date yesterday --membr <pos-export.xlsx> --pdf <redsys.pdf> --pdf <paycomet.pdf> --evidence <processor-evidence.json> --payload <daily-payload.json> --workbook <AFSA Ingresos.xlsx>` once.
4. Read the one-line JSON. Do not open the spreadsheets in the chat. Do not click Membr.

The reconcile script calls, in order, the unmodified scripts in `approved/`:

- `afsa_checks.py export --business-date YYYY-MM-DD [--slack-on-fail] pos-export.xlsx`
- `afsa_checks.py dates --business-date YYYY-MM-DD [--slack-on-fail] [--evidence JSON] PDF...`
- `update_workbook.py SOURCE.xlsx PAYLOAD.json OUTPUT.xlsx`
- `afsa_checks.py final --business-date YYYY-MM-DD [--since ISO] [--slack-on-fail]`
- `afsa_checks.py gaps --business-date <the next day> [--slack-on-fail]`

`dates` does not produce the bank total. That total has to already be in `daily-payload.json`, and the POS fields in that file have to match `export` to the cent. This template does not invent the total and does not apply a tolerance. A hash mismatch on the approved files is `CHECKS_UNAVAILABLE`.

`final` reads `/root/.hermes/automation/af-ingresos/last-success.json`. Write that file only after the original Drive workbook has been read back. This no-agent job does not upload to Drive.

Tell the client one of three things, and only after `final` PASSes: verified and the difference is zero; verified but Membr card and the processor total differ (what each side shows, and to look the receipts up in Membr or the Paycomet and Redsys reports); or not verified, with no figure. Never adjust a platform amount.
