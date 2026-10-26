"""Feed downloaded files to the approved AFSA checks. Do not invent the day.

The template does not contain afsa_checks.py, update_workbook.py, the
membr-card-reconciliation skill, or references/af-ingresos-daily.md. Until
those are on the client computer, a day is unverified and nothing is written.

No tolerance is applied here. The on-screen total must equal the sum of the
amount column exactly. Platform figures are never adjusted.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .approved import find_approved, run_export, run_update
from .runtime import client_root, sha256_file
from .source_gate import GateResult, inspect_xlsx
from .workbook_guard import apply_day_row

OUTCOME_MATCH = "verified_match"
OUTCOME_DISAGREE = "verified_disagree"
OUTCOME_UNVERIFIED = "unverified"


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


def _review_refs(*sources: tuple[str, GateResult, bool]) -> tuple[list[str], list[str]]:
    duplicates: list[str] = []
    unclassified: list[str] = []
    for name, gate, present in sources:
        if not present or gate.status != "OK":
            continue
        duplicates.extend(f"{name}:{ref}" for ref in gate.duplicates)
        unclassified.extend(f"{name}:{ref}" for ref in gate.unclassified)
    return duplicates, unclassified


def _source_label(result: GateResult, present: bool) -> str:
    if not present or result.check_state == "not_checked":
        return "not_checked"
    if result.status != "OK" or result.duplicates or result.unclassified:
        return "mismatch"
    return "checked"


def _unverified(business: str, reason: str, sources: dict, **extra) -> dict:
    payload = {
        "business_date": business,
        "status": extra.pop("status", reason if reason.isupper() else "NEEDS_CONFIRMATION"),
        "reason": reason,
        "outcome": OUTCOME_UNVERIFIED,
        "figures_final": False,
        "confirmed_write": False,
        "sources_state": sources,
        "items": [],
        "review_refs": extra.pop("review_refs", []),
        "phrase": extra.pop("phrase", ""),
        "tolerance": None,
    }
    payload.update(extra)
    return payload


def review_day(
    *,
    business_date: date,
    membr: Path | None,
    paycomet: Path | None,
    harlands: Path | None,
    workbook: Path | None,
    screen_count_text: str | None = None,
    screen_total_text: str | None = None,
    approved: dict | None = None,
) -> dict:
    """Check the files, then call the approved scripts if every source is real."""
    business = business_date.isoformat()
    membr_present = membr is not None and membr.is_file() and membr.stat().st_size > 0
    pay_present = paycomet is not None and paycomet.is_file() and paycomet.stat().st_size > 0
    har_present = harlands is not None and harlands.is_file() and harlands.stat().st_size > 0
    membr_gate = inspect_xlsx(
        membr,
        business_date=business_date,
        screen_count_text=screen_count_text,
        screen_total_text=screen_total_text,
        require_screen=True,
    )
    pay_gate = (
        inspect_xlsx(paycomet, business_date=business_date)
        if pay_present
        else GateResult("NEEDS_CONFIRMATION", "missing", rows=None, check_state="not_checked")
    )
    har_gate = (
        inspect_xlsx(harlands, business_date=business_date)
        if har_present
        else GateResult("NEEDS_CONFIRMATION", "missing", rows=None, check_state="not_checked")
    )
    sources = {
        "membr": _source_label(membr_gate, membr_present),
        "paycomet": _source_label(pay_gate, pay_present),
        "harlands": _source_label(har_gate, har_present),
    }
    if membr_gate.status != "OK":
        return _unverified(
            business,
            membr_gate.reason,
            sources,
            status=membr_gate.status,
            unparsed_count=membr_gate.unparsed_count,
        )
    for gate in (pay_gate, har_gate):
        if pay_present and gate is pay_gate and gate.status != "OK":
            return _unverified(business, gate.reason, sources, status=gate.status, unparsed_count=gate.unparsed_count)
        if har_present and gate is har_gate and gate.status != "OK":
            return _unverified(business, gate.reason, sources, status=gate.status, unparsed_count=gate.unparsed_count)
    duplicates, unclassified = _review_refs(
        ("membr", membr_gate, membr_present),
        ("paycomet", pay_gate, pay_present),
        ("harlands", har_gate, har_present),
    )
    if not pay_present or not har_present:
        return _unverified(
            business,
            "membr_only",
            sources,
            status="NEEDS_CONFIRMATION",
            phrase="Membr only, not cross-checked",
            review_refs=duplicates + unclassified,
            duplicates=duplicates,
            unclassified=unclassified,
        )
    if duplicates or unclassified:
        reason = "duplicate_ref" if duplicates else "unclassified"
        return _unverified(
            business,
            reason,
            sources,
            status="NEEDS_CONFIRMATION",
            review_refs=duplicates + unclassified,
            duplicates=duplicates,
            unclassified=unclassified,
        )
    found = approved if approved is not None else find_approved()
    if not found:
        return _unverified(business, "checks_unavailable", sources, status="CHECKS_UNAVAILABLE")
    export = run_export(
        found["checks"],
        business_date=business,
        membr=membr,
        paycomet=paycomet,
        harlands=harlands,
    )
    export_status = str(export.get("status") or "")
    if export_status not in {"match", "disagree"}:
        return _unverified(
            business,
            str(export.get("reason") or "checks_output"),
            sources,
            status="CHECKS_UNAVAILABLE",
            approved_spec=str(found.get("spec") or ""),
        )
    items = export.get("items") if isinstance(export.get("items"), list) else []
    outcome = OUTCOME_MATCH if export_status == "match" else OUTCOME_DISAGREE
    row = export.get("row")
    row_number = export.get("row_number")
    cells = [str(cell) for cell in row] if isinstance(row, list) else None
    if not isinstance(row_number, int) or cells is None:
        return _unverified(business, "checks_output", sources, status="CHECKS_UNAVAILABLE")
    if workbook is None or not workbook.is_file():
        return _unverified(business, "workbook_missing", sources, status="NEEDS_CONFIRMATION")
    row_json = client_root() / "state" / f"row-{business}.json"

    def _writer() -> None:
        run_update(
            found["update"],
            workbook=workbook,
            business_date=business,
            row_number=row_number,
            cells=cells,
            row_json=row_json,
        )

    written = apply_day_row(workbook, row_number=row_number, cells=cells, writer=_writer)
    confirmed = bool(written.get("confirmed_write"))
    payload = {
        "business_date": business,
        "status": "CONFIRMED" if confirmed else "FAILED",
        "reason": written.get("reason") or "ok",
        "outcome": outcome if confirmed else OUTCOME_UNVERIFIED,
        "figures_final": bool(confirmed and outcome in {OUTCOME_MATCH, OUTCOME_DISAGREE}),
        "confirmed_write": confirmed,
        "sources_state": sources,
        "items": items if confirmed else [],
        "review_refs": [],
        "phrase": "",
        "tolerance": None,
        "readback": {
            "ok": confirmed,
            "row_number": row_number,
            "cells": cells if confirmed else [],
        },
        "workbook": str(workbook),
        "workbook_sha256": written.get("workbook_sha256") or "",
        "backup": written.get("backup") or "",
        "backup_sha256": written.get("backup_sha256") or "",
        "approved_spec": str(found.get("spec") or ""),
        "spec_sha256": found.get("spec_sha256") or "",
    }
    if not confirmed:
        payload["figures_final"] = False
        payload["items"] = []
        payload["reason"] = written.get("reason") or "readback_mismatch"
    return payload
