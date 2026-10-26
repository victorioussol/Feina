"""Small xlsx reader and writer.

Enough for Membr-style exports (shared strings or inline strings, numbers)
and for the AFSA workbook this package writes. Exotic Excel features are
left untouched and reported as an empty sheet rather than guessed.
"""

from __future__ import annotations

import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def _col_row(ref: str) -> tuple[int, int]:
    letters = "".join(ch for ch in ref if ch.isalpha())
    digits = "".join(ch for ch in ref if ch.isdigit())
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch.upper()) - 64)
    return col - 1, (int(digits) - 1 if digits else 0)


def _ref(col: int, row: int) -> str:
    n = col + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def read_xlsx(path: Path) -> list[list[list[str]]]:
    """Return a list of sheets, each a list of rows of strings."""
    return list(read_xlsx_named(path).values())


def read_xlsx_named(path: Path) -> dict[str, list[list[str]]]:
    """Sheets by name. Cell text stays in the returned tables."""
    with zipfile.ZipFile(path) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(_q("si")):
                texts = [t.text or "" for t in si.iter(_q("t"))]
                shared.append("".join(texts))
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        sheets: dict[str, list[list[str]]] = {}
        for sheet in workbook.find(_q("sheets")).findall(_q("sheet")):
            name = sheet.attrib.get("name") or ""
            rid = sheet.attrib.get(f"{{{REL}}}id")
            target = rel_map[rid]
            if not target.startswith("xl/"):
                target = "xl/" + target.lstrip("/")
            sheets[name] = _read_sheet(ET.fromstring(zf.read(target)), shared)
    return sheets


def count_data_rows(path: Path, sheet_name: str) -> int | None:
    """Non-empty rows after the first row of sheet_name.

    The first row is the header and is not counted. None means that sheet is
    absent. Cell values are not returned.
    """
    tables = read_xlsx_named(path)
    if sheet_name not in tables:
        return None
    rows = tables[sheet_name]
    if len(rows) <= 1:
        return 0
    count = 0
    for row in rows[1:]:
        if any(str(cell).strip() for cell in row):
            count += 1
    return count


def _read_sheet(root: ET.Element, shared: list[str]) -> list[list[str]]:
    grid: dict[int, dict[int, str]] = {}
    max_row = 0
    max_col = 0
    for cell in root.iter(_q("c")):
        ref = cell.attrib.get("r")
        if not ref:
            continue
        col, row = _col_row(ref)
        value = _cell_value(cell, shared)
        grid.setdefault(row, {})[col] = value
        max_row = max(max_row, row)
        max_col = max(max_col, col)
    if not grid:
        return []
    table = []
    for r in range(max_row + 1):
        table.append([grid.get(r, {}).get(c, "") for c in range(max_col + 1)])
    return table


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        texts = [t.text or "" for t in cell.iter(_q("t"))]
        return "".join(texts)
    node = cell.find(_q("v"))
    if node is None or node.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(node.text)]
        except (IndexError, ValueError):
            return ""
    return node.text


def write_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    """Write a workbook. Cell values are strings, numbers, or dates."""
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(sheets)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types(len(names)))
        zf.writestr("_rels/.rels", _root_rels())
        zf.writestr("xl/workbook.xml", _workbook(names))
        zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(names)))
        zf.writestr("xl/styles.xml", _styles())
        for index, name in enumerate(names, start=1):
            zf.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheets[name]))


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sheet_xml(rows: list[list[object]]) -> str:
    body = ["<?xml version='1.0' encoding='UTF-8'?>", f'<worksheet xmlns="{NS}"><sheetData>']
    for r, row in enumerate(rows):
        cells = []
        for c, value in enumerate(row):
            ref = _ref(c, r)
            if isinstance(value, bool):
                value = "true" if value else "false"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                continue
            if isinstance(value, (date, datetime)):
                text = value.isoformat()
            else:
                text = "" if value is None else str(value)
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(text)}</t></is></c>'
            )
        body.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    body.append("</sheetData></worksheet>")
    return "".join(body)


def _content_types(n_sheets: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for i in range(1, n_sheets + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f'<Types xmlns="{CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(overrides)
        + "</Types>"
    )


def _root_rels() -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f'<Relationships xmlns="{PKG_REL}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook(names: list[str]) -> str:
    sheets = []
    for i, name in enumerate(names, start=1):
        sheets.append(f'<sheet name="{_xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>')
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f'<workbook xmlns="{NS}" xmlns:r="{REL}">'
        f"<sheets>{''.join(sheets)}</sheets></workbook>"
    )


def _workbook_rels(n_sheets: int) -> str:
    rows = []
    for i in range(1, n_sheets + 1):
        rows.append(
            f'<Relationship Id="rId{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{i}.xml"/>'
        )
    rows.append(
        f'<Relationship Id="rId{n_sheets + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f'<Relationships xmlns="{PKG_REL}">{"".join(rows)}</Relationships>'
    )


def _styles() -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f'<styleSheet xmlns="{NS}"><fonts count="1"><font><sz val="11"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="1"><xf xfId="0"/></cellXfs></styleSheet>'
    )
