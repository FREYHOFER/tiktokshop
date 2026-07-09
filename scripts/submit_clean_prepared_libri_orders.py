#!/usr/bin/env python3
"""Submit only clean prepared TikTok order packages to Libri.

This wrapper intentionally skips packages with warnings, such as incomplete customer
addresses or missing EAN values. Duplicate protection is handled by
scripts/libri_customer_submit.py through .automation/libri_order_state.json.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


def clean(value: object) -> str:
    return str(value or "").strip()


def latest_run_dir(output_root: Path) -> Path | None:
    if not output_root.exists():
        return None
    candidates = [path for path in output_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def read_summary(run_dir: Path) -> list[dict[str, str]]:
    summary_path = run_dir / "orders_summary.csv"
    if not summary_path.exists():
        return []
    text = summary_path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(text.splitlines(), dialect=dialect))


def submit_order(order_dir: Path, env_path: Path, state_path: Path) -> int:
    script_path = Path(__file__).resolve().parent / "libri_customer_submit.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--order-dir",
            str(order_dir),
            "--env",
            str(env_path),
            "--state",
            str(state_path),
        ],
        text=True,
    )
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit clean prepared TikTok order packages to Libri.")
    parser.add_argument("--output-root", default="outputs/order_automation")
    parser.add_argument("--run-dir", default="", help="Specific prepared-order run directory. Defaults to newest run dir.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--state", default=".automation/libri_order_state.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = Path(args.run_dir) if args.run_dir else latest_run_dir(Path(args.output_root))
    if run_dir is None:
        print("No prepared order run directory found.")
        return 0

    rows = read_summary(run_dir)
    if not rows:
        print(f"No orders_summary.csv found in {run_dir}; nothing to submit.")
        return 0

    submitted = 0
    skipped = 0
    failed = 0
    for row in rows:
        order_id = clean(row.get("order_id"))
        status = clean(row.get("automation_status"))
        if status != "prepared":
            print(f"Skipping order {order_id or '<missing>'}: status is {status or '<empty>'}.")
            skipped += 1
            continue
        order_dir = run_dir / order_id
        if not order_dir.exists():
            print(f"Skipping order {order_id}: prepared order directory is missing.")
            skipped += 1
            continue
        print(f"Submitting clean prepared order {order_id} to Libri.")
        rc = submit_order(order_dir, Path(args.env), Path(args.state))
        if rc == 0:
            submitted += 1
        else:
            failed += 1

    print(f"Libri clean-order submissions: {submitted} submitted/skipped-as-duplicate, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
