#!/usr/bin/env python3
"""Test double. Splices one row, or rewrites the file when asked to misbehave."""

import json
import os
import sys
from pathlib import Path


def _arg(name: str) -> str:
    return sys.argv[sys.argv.index(name) + 1]


workbook = Path(_arg("--workbook"))
row_number = int(_arg("--row-number"))
payload = json.loads(Path(_arg("--row-json")).read_text(encoding="utf-8"))
cells = [str(cell) for cell in payload["cells"]]
mode = os.environ.get("FEINA_TEST_UPDATE", "splice")

scripts = Path(__file__).resolve().parents[3] / "files" / "scripts"
sys.path.insert(0, str(scripts))

if mode == "rewrite":
    from feina_client.xlsxio import read_xlsx, write_xlsx

    sheets = read_xlsx(workbook)
    header = sheets[0][0] if sheets and sheets[0] else []
    write_xlsx(workbook, {"AFSA": [header, cells]})
else:
    from feina_client.workbook_guard import splice_row

    splice_row(workbook, row_number, cells)
