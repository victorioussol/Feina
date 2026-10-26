# Selectors checked on 26 Oct 2026

One supervised `--inspect` on the club admin, then Membr Insights. `club_base_url` still has to replace `REPLACE_CLUB` before the script will run. The script opens that host and `allowed_hosts` only.

| Step | What the live run showed | What is still open |
|---|---|---|
| Hosts | Club admin, then a new tab on `insights.eu.membr.com` | The real club host string. No other host is allowed |
| Tabs | Sidebar `Informes` is `a.Aside-menu-link.has-subMenu`. The child `a.Aside-submenu-link` (`sendTokenToReportBuilder`) opens Insights at `/home` | The script opens its own tab and closes only tabs it opened |
| My Reports | Insights top nav: My Data, My Reports | |
| Transaction Reports | Categories include Access, Booking, Email, Member, Package, Prospect Reports, Session Packs, Transaction Reports, PT Reports | |
| POS Transactions | Exact label. Siblings on that menu: Cash Register, Past Transactions | |
| Dates | `input[name='from']` and `input[name='until']`, plain `YYYY-MM-DD` fill. Export metadata showed 00:00:00 and 23:59:59 | Whether that filter is UTC or Europe/Madrid. Manifest field `date_filter_timezone` stays `unverified`. Download-time metadata on the export is UTC |
| Gym | Select Gyms shows 2 gyms selected. The config name is `Anytime Fitness Sant Adrià`. The run stops with `GYM_FILTER_UNVERIFIED` unless the screen shows only that name before Run Report | The remove control was not given a CSS selector in the live notes. The script clicks an accessible `Remove {gym}` control and stops if the read-back is anything else |
| Run Report | Button text `Run Report`. Wait until `<b>N</b> total rows` has settled | |
| On-screen count | `N` is stored on the manifest. There is no money total. `Oops, an error has occurred` beside `0 total rows` is a failed run | |
| Download | `Download Report` opens a menu: (.csv), (.json), (.xlsx). The script clicks `Download Report (.xlsx)` and keeps Membr's bytes | |
| Saved file | `runs/<date>/pos-export.xlsx` plus sha256. Data rows are the non-empty rows after the header on sheet `Report`. A mismatch with `N` is `SCREEN_MISMATCH`. Both counts 0 is `EMPTY_DAY_NEEDS_CONFIRMATION` | |
| Workbook names | Sheets `Report` and `Report Meta Data`. Report name `POS Transaction` | `afsa_checks.py` (vendored, unmodified) accepts `Informe`, `Informe Meta Data`, and `Transaccion Punto de Venta`. A download OK is not an export PASS |
| Session | The dashboard versus the login form or a captcha. Login is in page storage | Cookies seen were `__stripe_*`, `_hj*`, `AWSALB*`. They are not a login signal |
| member_payments | Disabled | The whole report |
| direct_debits | Disabled. Harlands is a separate inbox file | The whole report |

`--inspect` waits for visible controls and for network idle, then writes `runs/<date>/manifest.json` with menus, inputs, and buttons. It does not download and it does not log in.
