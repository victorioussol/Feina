# Selectors that still need the supervised inspect run

Nothing in this file was checked against Vince's live Membr. The script refuses to run while `club_base_url` still contains `REPLACE_CLUB`.

| Step | What we know from public docs or the brief | What is a guess |
|---|---|---|
| Club host | Staff sign in at `yourclub.membr.com` | The real host string for Sant Adrià |
| Reports → Membr Report | Zendesk says the left nav is Reports, then Membr Report | Spanish labels, and every CSS selector |
| My Reports | The EU Report Builder manual names My Reports and My Data | "Mis informes", and how the menu is marked up |
| Transacción Punto de Venta | The AFSA job uses this Spanish name. The EU POS manual's English name is "POS Transactions Report" | Which of those strings the Spanish club actually shows |
| Date fields | The manual says dates are listed on the left and open a date picker | `input[name='dateFrom']` and `input[name='dateTo']` |
| Run Report | The EU manual tells the user to click Run Report | "Ejecutar informe" and the button's selector |
| Download | The manual says Download exports all pages to Excel | `button:has-text('Download')`, Descargar, Export, Excel |
| On-screen count and total | The file is checked against the number Membr shows | `.report-row-count`, `[data-row-count]`, `.report-total`, `[data-report-total]` |
| member_payments | Not named as a specific menu entry in the manuals we used | The whole report. It ships `enabled: false` |
| direct_debits | Same | The whole report. It ships `enabled: false` |
| Cookie names | A session lasts about 24 hours in Vince's history. That duration is observed, not documented | `PHPSESSID`, `membr_session`, `MEMBRSESSID`, `remember_me`, `access_token` |

`--inspect` writes `runs/<date>/manifest.json` plus page snapshots (tags, ids, names, visible labels). It does not download and it does not log in. Fix `membr.reports.yaml` from that file, then run one real download while someone watches.
