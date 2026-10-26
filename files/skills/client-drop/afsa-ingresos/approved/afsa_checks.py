#!/root/.hermes/tools/python-3.14.7+20260901-linux-x64/bin/python3
"""Deterministic AFSA Ingresos run checks (Feina, approved by Victor 2026-10-20).

  afsa_checks.py dates --business-date YYYY-MM-DD [--evidence JSON ...] PDF...
      PASS only if every payment-report transaction date equals the business date:
      Paycomet: every date in the 'Detalle de Operaciones' table; other PDFs (Redsys slips):
      every dd/mm/yyyy or dd/mm/yy date on the slips, plus Redsys 'Fecha : dd.mm.yy' dates (dotted
      format, only after a 'Fecha :' label so amounts like 59.90 are never read as dates). Also FAILS if a PDF is byte-identical to a
      PDF stored under another, already verified business date's run folder (re-used report), or if no
      transaction date can be read. --evidence: payment-evidence JSON whose operations[].date are
      checked the same way.
  afsa_checks.py final --business-date YYYY-MM-DD [--since ISO]
      PASS only if last-success.json is for this business date, read-back verified, for the
      original Drive ID, with an md5, and (with --since) completed after the run started.
      On PASS the date is recorded in verified-dates.json.
  afsa_checks.py gaps --business-date YYYY-MM-DD
      Lists dates from the ledger start up to the day BEFORE the business date with no verified row.
  afsa_checks.py export --business-date YYYY-MM-DD XLSX
      Membr 'Transaccion Punto de Venta' export (e.g. one Vince sent on Telegram): PASS only if its
      metadata period covers the whole business date, it was downloaded after that day ended, every
      row of that date is Anytime Fitness Sant Adria with a known status (Pagado/Devolver), and the
      required columns exist. Prints only aggregates: pos_total_net, pos_card, pos_noncard_net
      (signed line subtotals; card = 'Tarjeta'), line and receipt counts. No member data.
  --slack-on-fail (any check): on FAIL also post one content-free line to FEINA_VINCE_SLACK_WEBHOOK.
Prints one JSON line; exit 0 = PASS, 1 = FAIL, 2 = usage/IO error. Read-only except the ledger.
"""
import argparse, datetime as dt, hashlib, json, re, sys
from pathlib import Path

BASE = Path('/root/.hermes/automation/af-ingresos')
LEDGER = BASE / 'verified-dates.json'
DRIVE_ID = '1S8Il6uG1sDfpN3T9xSnMxiMKyVLpUHl0'
DATE_RE = re.compile(r'\b(\d{2})/(\d{2})/(\d{4}|\d{2})\b')
# Redsys slips print 'Fecha : 20.10.26'. Approved by Victor 2026-10-21; label-anchored so amounts never match.
SLIP_DOT_RE = re.compile(r'Fecha\s*:\s*(\d{2})\.(\d{2})\.(\d{2,4})')
SLACK_ON_FAIL = False

def slack_fail(check, bd, n):
    import os, urllib.request
    hook = os.environ.get('FEINA_VINCE_SLACK_WEBHOOK')
    env = Path('/root/.hermes/.env')
    if not hook and env.exists():
        for l in env.read_text().splitlines():
            if l.startswith('FEINA_VINCE_SLACK_WEBHOOK='): hook = l.split('=', 1)[1].strip().strip('\'"')
    if not hook: return 'slack_not_configured'
    text = (f':x: AFSA Ingresos check FAIL: `{check}` for business date {bd} ({n} problem(s)). '
            f'Nothing was written to Drive. Details: runs/{bd}/ on feina-vince.')
    try:
        r = urllib.request.urlopen(urllib.request.Request(hook, json.dumps({'text': text}).encode(),
                                   {'Content-Type': 'application/json'}), timeout=20)
        return f'{r.status} {r.read().decode()[:10]}'
    except Exception as e: return f'slack_error:{type(e).__name__}'

def out(result, code, **kw):
    check = kw.pop('check')
    if result == 'FAIL' and SLACK_ON_FAIL:
        kw['slack'] = slack_fail(check, kw.get('business_date'), len(kw.get('problems') or kw.get('missing') or []))
    print(json.dumps({'check': check, 'result': result, **kw}, ensure_ascii=False))
    sys.exit(code)

def to_iso(d, m, y):
    y = int(y) + (2000 if len(y) == 2 else 0)
    try: return dt.date(y, int(m), int(d)).isoformat()
    except ValueError: return None

def pdf_dates(path):
    import pypdf
    text = '\n'.join((p.extract_text() or '') for p in pypdf.PdfReader(str(path)).pages)
    i = text.find('Detalle de Operaciones')
    if i >= 0:  # Paycomet: authoritative operation table only (header dates are print/send dates)
        seg = text[i:]
        rows = [l for l in seg.splitlines() if DATE_RE.search(l) and re.search(r'\d+,\d{2}\s*EUR', l)]
        return 'paycomet_detail', [to_iso(*DATE_RE.search(l).groups()) for l in rows]
    return 'slip_dates', [to_iso(*m) for m in DATE_RE.findall(text)] + [to_iso(*m) for m in SLIP_DOT_RE.findall(text)]

def ev_dates(path):
    d = json.loads(Path(path).read_text())
    found = []
    def walk(o):
        if isinstance(o, dict):
            if 'operations' in o and isinstance(o['operations'], list):
                for op in o['operations']:
                    v = str((op or {}).get('date') or '')
                    m = DATE_RE.search(v); iso = re.fullmatch(r'\d{4}-\d{2}-\d{2}', v[:10])
                    found.append(to_iso(*m.groups()) if m else (v[:10] if iso else None))
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(d)
    return found

def cmd_dates(a):
    bd = a.business_date; problems = []; details = []
    if not a.pdfs and not a.evidence:
        out('FAIL', 1, check='dates', business_date=bd, problems=['no payment files given'])
    run_dir = BASE / 'runs'
    others = {}
    verified_dates = set(load_ledger().get('verified', {}))
    for p in run_dir.glob('*/*.pdf'):  # a report already used for a VERIFIED other date must not be reused
        if p.parent.name != bd and p.parent.name in verified_dates:
            try: others.setdefault(hashlib.md5(p.read_bytes()).hexdigest(), set()).add(p.parent.name)
            except OSError: pass
    for p in a.pdfs:
        p = Path(p)
        try: kind, dates = pdf_dates(p); md5 = hashlib.md5(p.read_bytes()).hexdigest()
        except Exception as e: problems.append(f'{p.name}: unreadable ({type(e).__name__})'); continue
        bad = sorted({d for d in dates if d != bd}, key=str)
        if md5 in others: problems.append(f'{p.name}: byte-identical to report already used for {sorted(others[md5])}')
        if not dates: problems.append(f'{p.name}: no transaction dates readable')
        if bad: problems.append(f'{p.name}: transaction dates {bad} != {bd}')
        details.append({'file': p.name, 'kind': kind, 'transactions': len(dates), 'other_dates': bad})
    for e in a.evidence or []:
        try: dates = ev_dates(e)
        except Exception as ex: problems.append(f'{Path(e).name}: unreadable ({type(ex).__name__})'); continue
        bad = sorted({d for d in dates if d != bd}, key=str)
        if bad: problems.append(f'{Path(e).name}: operation dates {bad} != {bd}')
        details.append({'file': Path(e).name, 'kind': 'evidence_json', 'transactions': len(dates), 'other_dates': bad})
    out('FAIL' if problems else 'PASS', 1 if problems else 0, check='dates', business_date=bd, files=details, problems=problems)

def load_ledger():
    try: return json.loads(LEDGER.read_text())
    except FileNotFoundError: return {'start': None, 'verified': {}}

def cmd_final(a):
    bd = a.business_date; problems = []
    try: s = json.loads((BASE / 'last-success.json').read_text())
    except Exception as e: out('FAIL', 1, check='final', business_date=bd, problems=[f'last-success.json unreadable ({type(e).__name__})'])
    if s.get('business_date') != bd: problems.append(f"last-success.json is for {s.get('business_date')}, not {bd}")
    if s.get('report_readback_verified') is not True: problems.append('report_readback_verified is not true')
    if s.get('verified_drive_id') != DRIVE_ID: problems.append('verified_drive_id is not the original workbook')
    if not s.get('md5'): problems.append('no verified md5')
    if a.since:
        since = dt.datetime.fromisoformat(a.since)
        if since.tzinfo is None: since = since.replace(tzinfo=dt.timezone.utc)
        ts = s.get('completed_at') or s.get('verified_at')
        try:
            t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
            if t < since: problems.append(f'last-success.json was not updated during this run ({ts})')
        except Exception: problems.append('last-success.json has no valid completed_at/verified_at')
    if not problems:
        led = load_ledger(); led.setdefault('verified', {})[bd] = {'md5': s.get('md5'), 'recorded_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'source': 'afsa_checks final'}
        tmp = LEDGER.with_suffix('.tmp'); tmp.write_text(json.dumps(led, indent=2, sort_keys=True)); tmp.replace(LEDGER)
    out('FAIL' if problems else 'PASS', 1 if problems else 0, check='final', business_date=bd, problems=problems)

def gaps(bd):
    led = load_ledger(); start = led.get('start')
    if not start: return []
    have = set(led.get('verified', {}))
    d, end, miss = dt.date.fromisoformat(start), dt.date.fromisoformat(bd), []
    while d < end:
        if d.isoformat() not in have: miss.append(d.isoformat())
        d += dt.timedelta(days=1)
    return miss

EXPORT_COLS = ['Fecha de la transacción', 'Estado de transacción', 'Tipo de pago', 'Subtotal', 'Nombre del gimnasio', 'Número de recibo']
GYM = 'Anytime Fitness Sant Adria'

def cmd_export(a):
    from decimal import Decimal
    import openpyxl
    bd = a.business_date; day = dt.date.fromisoformat(bd); problems = []
    try: wb = openpyxl.load_workbook(a.xlsx, data_only=True, read_only=True)
    except Exception as e: out('FAIL', 1, check='export', business_date=bd, problems=[f'export unreadable ({type(e).__name__})'])
    if 'Informe' not in wb.sheetnames or 'Informe Meta Data' not in wb.sheetnames:
        out('FAIL', 1, check='export', business_date=bd, problems=['not a Membr Transaccion Punto de Venta export (sheets missing)'])
    meta = [[c for c in r] for r in wb['Informe Meta Data'].iter_rows(min_row=1, max_row=2, values_only=True)]
    md = dict(zip(meta[0], meta[1])) if len(meta) == 2 else {}
    def ts(v):
        try: return v if isinstance(v, dt.datetime) else dt.datetime.fromisoformat(str(v))
        except Exception: return None
    if md.get('Nombre Informe') != 'Transaccion Punto de Venta': problems.append('report name is not Transaccion Punto de Venta')
    f, t, dl = ts(md.get('Fecha de')), ts(md.get('Fecha hasta')), ts(md.get('Fecha descargado'))
    start, end = dt.datetime.combine(day, dt.time(0, 0)), dt.datetime.combine(day, dt.time(23, 59, 59))
    if not f or not t or f > start or t < end: problems.append('export period does not cover the whole business date')
    if not dl or dl < start + dt.timedelta(days=1): problems.append('export was downloaded before the business date ended')
    rows = wb['Informe'].iter_rows(values_only=True); hdr = list(next(rows, []) or [])
    miss = [c for c in EXPORT_COLS if c not in hdr]
    if miss: out('FAIL', 1, check='export', business_date=bd, problems=problems + [f'missing columns {miss}'])
    ix = {c: hdr.index(c) for c in EXPORT_COLS}
    total = card = Decimal('0'); lines = other_gym = bad_status = other_dates = 0; receipts = set()
    for r in rows:
        if not r or all(v is None for v in r): continue
        when = ts(r[ix['Fecha de la transacción']])
        if not when: problems.append('row with unreadable transaction date'); continue
        if when.date() != day: other_dates += 1; continue
        if r[ix['Nombre del gimnasio']] != GYM: other_gym += 1; continue
        if r[ix['Estado de transacción']] not in ('Pagado', 'Devolver'): bad_status += 1; continue
        v = Decimal(str(r[ix['Subtotal']] or 0)); lines += 1; receipts.add(r[ix['Número de recibo']]); total += v
        if r[ix['Tipo de pago']] == 'Tarjeta': card += v
    if other_gym: problems.append(f'{other_gym} row(s) on the business date belong to another gym')
    if bad_status: problems.append(f'{bad_status} row(s) on the business date have an unexpected status')
    q = lambda d: str(d.quantize(Decimal('0.01')))
    out('FAIL' if problems else 'PASS', 1 if problems else 0, check='export', business_date=bd, gym=GYM,
        transaction_lines=lines, receipts=len(receipts), rows_other_dates=other_dates,
        pos_total_net=q(total), pos_card=q(card), pos_noncard_net=q(total - card), problems=problems)

def cmd_gaps(a):
    m = gaps(a.business_date)
    out('FAIL' if m else 'PASS', 1 if m else 0, check='gaps', business_date=a.business_date, missing=m)

if __name__ == '__main__':
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest='cmd', required=True)
    x = sp.add_parser('dates'); x.add_argument('--business-date', required=True); x.add_argument('--evidence', action='append'); x.add_argument('pdfs', nargs='*')
    y = sp.add_parser('final'); y.add_argument('--business-date', required=True); y.add_argument('--since')
    z = sp.add_parser('gaps'); z.add_argument('--business-date', required=True)
    w = sp.add_parser('export'); w.add_argument('--business-date', required=True); w.add_argument('xlsx')
    for q in (x, y, z, w): q.add_argument('--slack-on-fail', action='store_true')
    a = p.parse_args(); SLACK_ON_FAIL = a.slack_on_fail
    try: dt.date.fromisoformat(a.business_date)
    except ValueError: print(json.dumps({'result': 'ERROR', 'problems': ['bad --business-date']})); sys.exit(2)
    {'dates': cmd_dates, 'final': cmd_final, 'gaps': cmd_gaps, 'export': cmd_export}[a.cmd](a)
