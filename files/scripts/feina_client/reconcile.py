"""Match Membr, Paycomet and Harlands rows and write the AFSA workbook.

The workbook is only successful when it is read back and the business-date
row matches what was just written. A missing read-back is a failed run.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .runtime import sha256_file
from .xlsxio import read_xlsx, write_xlsx

GAP = Decimal("5.00")

CARD_WORDS = ("tarjeta", "card", "visa", "mastercard", "paycomet", "redsys", "tpv")
DEBIT_WORDS = ("domicili", "direct debit", "harlands", "adeudo", "sepa")
REFUND_WORDS = ("reembolso", "refund", "devoluc", "chargeback")
PAID_WORDS = ("paid", "ok", "collected", "cobrado", "pagado", "success", "complet")
FAILED_WORDS = ("fail", "rechaz", "unpaid", "bounce", "impag", "devuelto", "error")


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.strip().lower().split())


def parse_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip().replace("€", "").replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt, size in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10), ("%d-%m-%Y", 10), ("%d/%m/%y", 8)):
        try:
            return datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def _cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


@dataclass
class Line:
    source: str
    when: date
    amount: Decimal
    method: str = ""
    ref: str = ""
    status: str = ""
    member_ref: str = ""

    @property
    def cents(self) -> int:
        return _cents(self.amount)

    def match_cents(self) -> int:
        if self.kind() == "refund":
            return abs(self.cents)
        return self.cents

    def signed_amount(self) -> Decimal:
        if self.kind() == "refund":
            return -abs(self.amount)
        return self.amount

    def kind(self) -> str:
        blob = fold(f"{self.method} {self.status}")
        if any(word in blob for word in REFUND_WORDS) or self.amount < 0:
            return "refund"
        if any(word in blob for word in DEBIT_WORDS):
            return "debit"
        if any(word in blob for word in CARD_WORDS):
            return "card"
        return "other"


@dataclass
class Mismatch:
    kind: str
    amount: str
    ref: str
    source: str
    member_ref: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "amount": self.amount,
            "ref": self.ref,
            "source": self.source,
            "member_ref": self.member_ref,
        }


@dataclass
class Reconciliation:
    business_date: str
    membr_total: Decimal
    paycomet_total: Decimal
    harlands_total: Decimal
    mismatches: list[Mismatch] = field(default_factory=list)
    failed_debits: list[Mismatch] = field(default_factory=list)
    paycomet_present: bool = False
    harlands_present: bool = False

    def public_mismatches(self) -> list[dict]:
        """Client summary rows. Member refs stay off this list."""
        rows = []
        for item in self.mismatches:
            rows.append(
                {"kind": item.kind, "amount": item.amount, "ref": item.ref, "source": item.source}
            )
        return rows


def _pair(left: list[Line], right: list[Line], gap: Decimal) -> tuple[list[Line], list[Line]]:
    used: set[int] = set()
    unmatched_left: list[Line] = []
    gap_cents = _cents(gap)
    for item in left:
        found = None
        for index, other in enumerate(right):
            if index in used:
                continue
            if item.match_cents() == other.match_cents():
                found = index
                break
        if found is None:
            for index, other in enumerate(right):
                if index in used:
                    continue
                if abs(item.match_cents() - other.match_cents()) <= gap_cents:
                    found = index
                    break
        if found is None:
            unmatched_left.append(item)
        else:
            used.add(found)
    unmatched_right = [other for index, other in enumerate(right) if index not in used]
    return unmatched_left, unmatched_right


def _is_failed(status: str) -> bool:
    blob = fold(status)
    if not blob:
        return False
    if any(word in blob for word in PAID_WORDS) and not any(word in blob for word in FAILED_WORDS):
        return False
    return any(word in blob for word in FAILED_WORDS)


def reconcile_lines(
    membr: list[Line],
    paycomet: list[Line] | None,
    harlands: list[Line] | None,
    *,
    business_date: date,
    gap: Decimal = GAP,
    paycomet_required: bool = False,
    harlands_required: bool = False,
) -> Reconciliation:
    day = business_date
    membr_day = [row for row in membr if row.when == day]
    paycomet_day = [row for row in (paycomet or []) if row.when == day]
    harlands_day = [row for row in (harlands or []) if row.when == day]
    result = Reconciliation(
        business_date=day.isoformat(),
        membr_total=sum((row.amount for row in membr_day), Decimal("0.00")),
        paycomet_total=sum((row.amount for row in paycomet_day), Decimal("0.00")),
        harlands_total=sum((row.amount for row in harlands_day), Decimal("0.00")),
        paycomet_present=paycomet is not None,
        harlands_present=harlands is not None,
    )
    if paycomet is None:
        if paycomet_required:
            result.mismatches.append(Mismatch("source_missing", "0.00", "paycomet", "paycomet"))
    else:
        cards = [row for row in membr_day if row.kind() in {"card", "refund"}]
        left, right = _pair(cards, paycomet_day, gap)
        for row in left:
            result.mismatches.append(
                Mismatch("unmatched_membr_card", f"{row.amount:.2f}", row.ref, "membr")
            )
        for row in right:
            result.mismatches.append(
                Mismatch("unmatched_paycomet", f"{row.amount:.2f}", row.ref, "paycomet")
            )
        card_total = sum((row.signed_amount() for row in cards), Decimal("0.00"))
        pay_total = sum((row.signed_amount() for row in paycomet_day), Decimal("0.00"))
        diff = abs(card_total - pay_total)
        if diff > gap:
            result.mismatches.append(
                Mismatch("total_gap", f"{diff:.2f}", "card-vs-paycomet", "totals")
            )
    if harlands is None:
        if harlands_required:
            result.mismatches.append(Mismatch("source_missing", "0.00", "harlands", "harlands"))
    else:
        debits = [row for row in membr_day if row.kind() == "debit"]
        left, right = _pair(debits, harlands_day, gap)
        for row in left:
            result.mismatches.append(
                Mismatch("unmatched_membr_debit", f"{row.amount:.2f}", row.ref, "membr")
            )
        for row in right:
            if _is_failed(row.status):
                continue
            result.mismatches.append(
                Mismatch("unmatched_harlands", f"{row.amount:.2f}", row.ref, "harlands")
            )
        for row in harlands_day:
            if _is_failed(row.status):
                item = Mismatch(
                    "failed_debit",
                    f"{row.amount:.2f}",
                    row.ref,
                    "harlands",
                    member_ref=row.member_ref,
                )
                result.failed_debits.append(item)
                result.mismatches.append(
                    Mismatch("failed_debit", f"{row.amount:.2f}", row.ref, "harlands")
                )
    return result


HEADER_ALIASES = {
    "date": ("fecha", "date", "transaction date", "f. valor"),
    "amount": ("importe", "amount", "total", "monto"),
    "method": ("metodo de pago", "método de pago", "payment method", "tipo", "method"),
    "ref": ("recibo", "receipt", "numero", "número", "pedido", "order", "referencia", "reference"),
    "status": ("estado", "status", "resultado"),
    "member": ("socio", "member", "member number", "id socio"),
}


def _header_map(header: list[str]) -> dict[str, int]:
    folded = [fold(cell) for cell in header]
    mapping: dict[str, int] = {}
    for key, aliases in HEADER_ALIASES.items():
        for index, cell in enumerate(folded):
            if cell in {fold(alias) for alias in aliases}:
                mapping[key] = index
                break
    return mapping


def lines_from_table(table: list[list[str]], source: str) -> list[Line]:
    if not table:
        return []
    mapping = _header_map(table[0])
    if "amount" not in mapping or "date" not in mapping:
        return []
    lines: list[Line] = []
    for raw in table[1:]:
        if not any(str(cell).strip() for cell in raw):
            continue

        def cell(key: str) -> str:
            index = mapping.get(key)
            if index is None or index >= len(raw):
                return ""
            return str(raw[index]).strip()

        when = parse_date(cell("date"))
        amount = parse_amount(cell("amount"))
        if when is None or amount is None:
            continue
        lines.append(
            Line(
                source=source,
                when=when,
                amount=amount,
                method=cell("method"),
                ref=cell("ref"),
                status=cell("status"),
                member_ref=cell("member"),
            )
        )
    return lines


def lines_from_xlsx(path: Path, source: str) -> list[Line]:
    sheets = read_xlsx(path)
    if not sheets:
        return []
    return lines_from_table(sheets[0], source)


RESUMEN_HEADER = [
    "night",
    "business_date",
    "membr_total",
    "paycomet_total",
    "harlands_total",
    "mismatch_count",
    "confirmed",
]


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def write_workbook(
    path: Path,
    *,
    night: str,
    result: Reconciliation,
    source_hashes: dict[str, str],
) -> dict:
    existing = {"Resumen": [RESUMEN_HEADER], "Descuadres": [["business_date", "kind", "amount", "ref", "source"]], "Control": [["key", "value"]]}
    if path.is_file():
        sheets = read_xlsx(path)
        names = ["Resumen", "Descuadres", "Control"]
        for index, name in enumerate(names):
            if index < len(sheets) and sheets[index]:
                existing[name] = sheets[index]
    resumen = [row for row in existing["Resumen"] if not row or row[0] == "night" or (len(row) > 1 and row[1] != result.business_date)]
    if not resumen or resumen[0] != RESUMEN_HEADER:
        resumen = [RESUMEN_HEADER] + [row for row in resumen if row and row[0] != "night"]
    row = [
        night,
        result.business_date,
        _money(result.membr_total),
        _money(result.paycomet_total),
        _money(result.harlands_total),
        str(len(result.public_mismatches())),
        "yes",
    ]
    resumen.append(row)
    previous = existing["Descuadres"] or [["business_date", "kind", "amount", "ref", "source"]]
    header = previous[0] if previous and previous[0] and previous[0][0] == "business_date" else ["business_date", "kind", "amount", "ref", "source"]
    kept = [drow for drow in previous[1:] if drow and drow[0] != result.business_date]
    descuadres = [header] + kept
    for item in result.public_mismatches():
        descuadres.append([result.business_date, item["kind"], item["amount"], item["ref"], item["source"]])
    control = [["key", "value"], ["night", night], ["business_date", result.business_date]]
    for name, digest in sorted(source_hashes.items()):
        control.append([f"sha256:{name}", digest])
    write_xlsx(path, {"Resumen": resumen, "Descuadres": descuadres, "Control": control})
    readback = verify_workbook(path, night=night, business_date=result.business_date, expected=row)
    return {
        "confirmed_write": readback["ok"],
        "workbook_sha256": sha256_file(path),
        "readback": readback,
        "path": str(path),
    }


def verify_workbook(path: Path, *, night: str, business_date: str, expected: list[str] | None = None) -> dict:
    sheets = read_xlsx(path)
    if not sheets or not sheets[0]:
        return {"ok": False, "reason": "readback_mismatch"}
    found = None
    for row in sheets[0][1:]:
        if len(row) >= 2 and row[1] == business_date:
            found = row
    if found is None:
        return {"ok": False, "reason": "readback_mismatch", "business_date": business_date}
    if expected is not None and [str(cell) for cell in found[: len(expected)]] != [str(cell) for cell in expected]:
        return {"ok": False, "reason": "readback_mismatch", "business_date": business_date}
    if found[0] != night or found[1] != business_date:
        return {"ok": False, "reason": "readback_mismatch", "business_date": business_date}
    return {
        "ok": True,
        "reason": "ok",
        "night": found[0],
        "business_date": found[1],
        "membr_total": found[2] if len(found) > 2 else "",
        "paycomet_total": found[3] if len(found) > 3 else "",
        "harlands_total": found[4] if len(found) > 4 else "",
        "mismatch_count": found[5] if len(found) > 5 else "",
        "confirmed": found[6] if len(found) > 6 else "",
    }


def verify_drive_readback(meta: dict, *, local_sha: str, madrid_day: date) -> tuple[bool, str]:
    """Check a Drive metadata dict the agent saved after uploading the workbook."""
    remote = str(meta.get("sha256") or meta.get("md5Checksum") or "")
    if meta.get("sha256") and remote != local_sha:
        return False, "hash_mismatch"
    modified = meta.get("modifiedTime")
    if not modified:
        return False, "not_today"
    when = datetime.fromisoformat(str(modified).replace("Z", "+00:00"))
    from .runtime import MADRID

    if when.astimezone(MADRID).date() != madrid_day:
        return False, "not_today"
    size = meta.get("size")
    if size is not None and int(size) <= 0:
        return False, "empty"
    return True, "ok"
