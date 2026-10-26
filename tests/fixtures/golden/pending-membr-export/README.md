# Future golden day that includes the Membr export

The 20 Oct 2026 golden day has no `Transaccion Punto de Venta` xlsx. `afsa_checks.py export` is not replayed for that day. C and E come from `daily-payload.json`.

Drop a later day's Membr export here as `pos-export.xlsx`, and put the business date in `business-date.txt` (one ISO date). The fixture test will run `afsa_checks.py export` on it. Until that file exists, the slot stays empty on purpose.
