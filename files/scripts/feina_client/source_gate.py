"""Stop conditions for a source file. Nothing here changes a platform figure.

A file that fails a check does not become an empty day and is not written as
€0. Rows that cannot be classified are returned only so they can be listed.
They are not treated as matched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .xlsxio import read_xlsx

REQUIRED = ("date", "amount", "ref", "method", "status")

HEADER_ALIASES = {
    "date": ("fecha", "date", "transaction date", "f. valor"),
    "amount": ("importe", "amount", "total", "monto"),
    "method": ("metodo de pago", "método de pago", "payment method", "tipo", "method"),
    "ref": ("recibo", "receipt", "numero", "número", "pedido", "order", "referencia", "reference"),
    "status": ("estado", "status", "resultado"),
    "member": ("socio", "member", "member number", "id socio"),
}

CLASS_WORDS = (
    "tarjeta",
    "card",
    "visa",
    "mastercard",
    "paycomet",
    "redsys",
    "tpv",
    "domicili",
    "direct debit",
    "harlands",
    "adeudo",
    "sepa",
    "reembolso",
    "refund",
    "devoluc",
    "chargeback",
)


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


@dataclass
class SourceRow:
    when: date
    amount: Decimal
    ref: str
    method: str
    status: str
    member_ref: str = ""

    def classified(self) -> bool:
        blob = fold(f"{self.method} {self.status}")
        return any(word in blob for word in CLASS_WORDS)


@dataclass
class GateResult:
    status: str
    reason: str
    rows: list[SourceRow] | None = None
    unparsed_count: int = 0
    duplicates: list[str] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)
    check_state: str = "mismatch"

    def blocks_write(self) -> bool:
        return self.status != "OK" or bool(self.duplicates) or bool(self.unclassified)


def _header_map(header: list[str]) -> dict[str, int]:
    folded = [fold(cell) for cell in header]
    mapping: dict[str, int] = {}
    for key, aliases in HEADER_ALIASES.items():
        wanted = {fold(alias) for alias in aliases}
        for index, cell in enumerate(folded):
            if cell in wanted:
                mapping[key] = index
                break
    return mapping


def _amount_token(text: str | None) -> Decimal | None:
    if not text:
        return None
    match = re.search(r"-?\d[\d.,]*", text)
    if not match:
        return None
    return parse_amount(match.group(0))


def _count_token(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    return int(match.group(0))


def inspect_table(
    table: list[list[str]] | None,
    *,
    business_date: date,
    screen_count_text: str | None = None,
    screen_total_text: str | None = None,
    require_screen: bool = False,
) -> GateResult:
    """Inspect one sheet. A failure returns rows=None, never an empty success."""
    if not table:
        return GateResult("NEEDS_CONFIRMATION", "empty_file", rows=None, check_state="mismatch")
    header = table[0]
    mapping = _header_map(header)
    missing = [name for name in REQUIRED if name not in mapping]
    if missing:
        return GateResult(
            "SOURCE_FORMAT_CHANGED",
            "missing_column:" + ",".join(missing),
            rows=None,
            check_state="mismatch",
        )
    body = [row for row in table[1:] if any(str(cell).strip() for cell in row)]
    if not body:
        return GateResult("NEEDS_CONFIRMATION", "zero_rows", rows=None, check_state="mismatch")

    parsed: list[SourceRow] = []
    unparsed = 0
    for raw in body:
        def cell(key: str, raw=raw) -> str:
            index = mapping[key]
            if index >= len(raw):
                return ""
            return str(raw[index]).strip()

        when = parse_date(cell("date"))
        amount = parse_amount(cell("amount"))
        ref = cell("ref")
        if when is None or amount is None or not ref:
            unparsed += 1
            continue
        member_index = mapping.get("member")
        member = ""
        if member_index is not None and member_index < len(raw):
            member = str(raw[member_index]).strip()
        parsed.append(
            SourceRow(
                when=when,
                amount=amount,
                ref=ref,
                method=cell("method"),
                status=cell("status"),
                member_ref=member,
            )
        )
    if unparsed:
        return GateResult(
            "PARSE_FAILED",
            "unparsed_rows",
            rows=None,
            unparsed_count=unparsed,
            check_state="mismatch",
        )
    dates = {row.when for row in parsed}
    if dates != {business_date}:
        return GateResult(
            "NEEDS_CONFIRMATION",
            "date_range",
            rows=None,
            check_state="mismatch",
        )
    day_rows = [row for row in parsed if row.when == business_date]
    if not day_rows:
        return GateResult("NEEDS_CONFIRMATION", "zero_rows", rows=None, check_state="mismatch")

    seen: dict[str, list[str]] = {}
    for row in day_rows:
        seen.setdefault(fold(row.ref), []).append(row.ref)
    duplicates: list[str] = []
    for refs in seen.values():
        if len(refs) < 2:
            continue
        for ref in refs:
            if ref not in duplicates:
                duplicates.append(ref)
    unclassified = [row.ref for row in day_rows if not row.classified()]

    if require_screen:
        count = _count_token(screen_count_text)
        total = _amount_token(screen_total_text)
        if count is None and total is None:
            return GateResult(
                "NEEDS_CONFIRMATION",
                "screen_not_captured",
                rows=None,
                duplicates=duplicates,
                unclassified=unclassified,
                check_state="mismatch",
            )
        file_total = sum((row.amount for row in day_rows), Decimal("0.00"))
        if count is not None and count != len(day_rows):
            return GateResult(
                "SCREEN_MISMATCH",
                "screen_count",
                rows=None,
                check_state="mismatch",
            )
        if total is not None and total != file_total:
            return GateResult(
                "SCREEN_MISMATCH",
                "screen_total",
                rows=None,
                check_state="mismatch",
            )
    return GateResult(
        "OK",
        "ok",
        rows=day_rows,
        duplicates=duplicates,
        unclassified=unclassified,
        check_state="checked",
    )


def inspect_xlsx(
    path: Path | None,
    *,
    business_date: date,
    screen_count_text: str | None = None,
    screen_total_text: str | None = None,
    require_screen: bool = False,
) -> GateResult:
    if path is None or not path.is_file() or path.stat().st_size == 0:
        return GateResult("NEEDS_CONFIRMATION", "empty_file", rows=None, check_state="not_checked")
    try:
        sheets = read_xlsx(path)
    except Exception:
        return GateResult("NEEDS_CONFIRMATION", "unreadable", rows=None, check_state="mismatch")
    table = sheets[0] if sheets else None
    result = inspect_table(
        table,
        business_date=business_date,
        screen_count_text=screen_count_text,
        screen_total_text=screen_total_text,
        require_screen=require_screen,
    )
    if result.reason == "empty_file":
        result.check_state = "not_checked"
    return result
