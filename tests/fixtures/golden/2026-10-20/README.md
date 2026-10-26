# Golden day: AFSA Ingresos, business date 2026-10-20 (sheet 2026, row 294)

`inputs/` holds the run folder `runs/2026-10-20/` from feina-vince, sanitized:
- PDFs: the masked card endings were replaced. Redsys slips now read `************0001` and Paycomet reads `************0002`. Nothing else changed (dates, amounts, auth/op refs, merchant/terminal ids, layout). Because of that, the PDF md5s differ from `file_md5` in processor-evidence.json/run-log.json. See fixture-manifest.json (`raw_md5` vs `md5`).
- JSON files (daily-payload, processor-evidence, run-log) are byte-identical to the originals. They hold no member data.
- MISSING: the Membr POS export (`Transaccion Punto de Venta2026-10-21 10-04-29.xlsx`) referenced in run-log.json was not on feina-vince's disk on 2026-10-26, so `afsa_checks.py export` can't be replayed. C/E come from daily-payload.json (aggregates already checked on 2026-10-21: 9 lines, 6 receipts, 135.49 / 159.49 / -24.00).

`expected.json` holds the header row (row 1) and row 294 (A..H): values/formulas, cached values, number formats, G font colour, fills, row height, H visibility and tabs, read from the workbook backup `2026-10-21_2026-10-22T0204.xlsx` (not included: it holds every other day).

Reproduce: afsa_checks.py dates → PASS. update_workbook.py → C:G values, formulas and caches identical. Known cosmetic difference: the Drive workbook's C:F number format is `#,##0.00_);[Red](#,##0.00)`, but the script writes `#,##0.00;[Red]-#,##0.00`. The conditional-format priorities differ too (6/10 vs 1/2, same order).
