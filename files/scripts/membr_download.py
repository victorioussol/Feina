#!/usr/bin/env python3
"""Download Membr Excel reports from the already logged-in club browser.

Exit 10 means LOGIN_REQUIRED. The script then stops. It does not log in.
Exit 2 means the run stopped: GYM_FILTER_UNVERIFIED, SCREEN_MISMATCH,
EMPTY_DAY_NEEDS_CONFIRMATION, or another failure. Exit 0 is OK or INSPECTED.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feina_client.browser import open_session  # noqa: E402
from feina_client.cliutil import enabled, host_ready, membr_config, resolve_business_date  # noqa: E402
from feina_client.download import NoProfile, exit_code, manifest_text, run_download  # noqa: E402
from feina_client.runtime import client_root  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Membr reports through the club UI")
    parser.add_argument("--date", default="yesterday")
    parser.add_argument("--config", default="")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    if not enabled("membr-download"):
        return 0
    cfg = membr_config(args.config or None)
    if not host_ready(cfg):
        sys.stderr.write("club_base_url is still the placeholder\n")
        return 2
    business = resolve_business_date(args.date)
    mode = "dry-run" if args.dry_run else "inspect" if args.inspect else "download"
    out = Path(args.out) if args.out else client_root() / "runs" / business
    try:
        session = open_session(cfg)
    except NoProfile:
        sys.stdout.write(manifest_text({"status": "LOGIN_REQUIRED", "reason": "no_profile", "files": []}) + "\n")
        return 10
    try:
        manifest = run_download(cfg, business_date=business, out_dir=out, session=session, mode=mode)
    finally:
        session.close()
    sys.stdout.write(manifest_text(manifest) + "\n")
    return exit_code(manifest)


if __name__ == "__main__":
    raise SystemExit(main())
