"""Write one existing day-row, then prove the rest of the sheet did not change.

This does not invent a workbook and it does not calculate the day's figures.
The cells come from the approved update script. If any other row changes, or
column H is hidden, the backup is restored.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .runtime import backup_file, sha256_file
from .xlsxio import NS, REL, read_xlsx

_ROW = re.compile(r"<row\b([^>]*)>(.*?)</row>|<row\b([^>]*)/>", re.DOTALL)


def _sheet_name(zf: zipfile.ZipFile) -> str:
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    sheet = workbook.find(f"{{{NS}}}sheets").find(f"{{{NS}}}sheet")
    rid = sheet.attrib.get(f"{{{REL}}}id")
    target = rel_map[rid]
    if not target.startswith("xl/"):
        target = "xl/" + target.lstrip("/")
    return target


def sheet_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read(_sheet_name(zf)).decode("utf-8")


def row_xml_map(xml: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for match in _ROW.finditer(xml):
        attrs = match.group(1) if match.group(1) is not None else match.group(3)
        number = re.search(r'\br="(\d+)"', attrs or "")
        if not number:
            continue
        found[int(number.group(1))] = match.group(0)
    return found


def column_h_hidden(xml: str) -> bool:
    """Column H is the 8th column. A hidden col that covers it fails the write."""
    for match in re.finditer(r"<col\b([^>]*)/?>", xml):
        attrs = match.group(1)
        low = re.search(r'\bmin="(\d+)"', attrs)
        high = re.search(r'\bmax="(\d+)"', attrs)
        hidden = re.search(r'\bhidden="([^"]+)"', attrs)
        if not low or not hidden:
            continue
        start = int(low.group(1))
        end = int(high.group(1)) if high else start
        if start <= 8 <= end and hidden.group(1) in {"1", "true"}:
            return True
    return False


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _ref(col: int, row_index: int) -> str:
    n = col + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row_index + 1}"


def row_xml(row_number: int, cells: list[str]) -> str:
    parts = []
    for index, value in enumerate(cells):
        ref = _ref(index, row_number - 1)
        parts.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(str(value))}</t></is></c>')
    return f'<row r="{row_number}">{"".join(parts)}</row>'


def splice_row(path: Path, row_number: int, cells: list[str]) -> None:
    """Replace one row element. Every other byte of the sheet XML stays put."""
    with zipfile.ZipFile(path) as zf:
        name = _sheet_name(zf)
        xml = zf.read(name).decode("utf-8")
        payload = {item: zf.read(item) for item in zf.namelist() if item != name}
    spans = row_xml_map(xml)
    current = spans.get(row_number)
    if current is None:
        raise LookupError(f"row {row_number} is not in the workbook")
    xml = xml.replace(current, row_xml(row_number, cells), 1)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item, data in payload.items():
            zf.writestr(item, data)
        zf.writestr(name, xml.encode("utf-8"))


def read_row_cells(path: Path, row_number: int) -> list[str] | None:
    sheets = read_xlsx(path)
    if not sheets:
        return None
    index = row_number - 1
    if index < 0 or index >= len(sheets[0]):
        return None
    return [str(cell) for cell in sheets[0][index]]


def apply_day_row(
    path: Path,
    *,
    row_number: int,
    cells: list[str],
    writer,
    backup_root: Path | None = None,
) -> dict:
    """Back up, let `writer` change the file, then read the day back.

    `writer` is the approved update script. On any failed check the backup
    is copied back over the workbook.
    """
    if not path.is_file():
        return {"confirmed_write": False, "reason": "workbook_missing"}
    if row_number < 1 or len(cells) < 8:
        return {"confirmed_write": False, "reason": "column_h_missing"}
    before_hash = sha256_file(path)
    before_xml = sheet_xml(path)
    if column_h_hidden(before_xml):
        return {"confirmed_write": False, "reason": "column_h_hidden", "workbook_sha256": before_hash}
    before_rows = row_xml_map(before_xml)
    if row_number not in before_rows:
        return {"confirmed_write": False, "reason": "row_missing", "workbook_sha256": before_hash}
    backup = backup_file(path, backup_root)
    try:
        writer()
    except Exception:
        if backup is not None:
            shutil.copy2(backup, path)
        return {"confirmed_write": False, "reason": "update_failed", "backup": str(backup) if backup else ""}
    after_xml = sheet_xml(path)
    if column_h_hidden(after_xml):
        if backup is not None:
            shutil.copy2(backup, path)
        return {"confirmed_write": False, "reason": "column_h_hidden", "backup": str(backup) if backup else ""}
    after_rows = row_xml_map(after_xml)
    for number, xml in before_rows.items():
        if number == row_number:
            continue
        if after_rows.get(number) != xml:
            if backup is not None:
                shutil.copy2(backup, path)
            return {"confirmed_write": False, "reason": "other_rows_changed", "backup": str(backup) if backup else ""}
    found = read_row_cells(path, row_number)
    expected = [str(cell) for cell in cells]
    if found is None or found[: len(expected)] != expected or len(found) < 8 or found[7] != expected[7]:
        if backup is not None:
            shutil.copy2(backup, path)
        return {"confirmed_write": False, "reason": "readback_mismatch", "backup": str(backup) if backup else ""}
    return {
        "confirmed_write": True,
        "reason": "ok",
        "row_number": row_number,
        "cells": expected,
        "workbook_sha256": sha256_file(path),
        "backup": str(backup) if backup else "",
        "backup_sha256": before_hash,
        "path": str(path),
    }
