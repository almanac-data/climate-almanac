#!/usr/bin/env python3
"""Reachability checker — the seed of automated monitoring.

For each catalog entry, probes source.canonical_url and reports whether the
declared `status` still matches reality. Read-only: it prints a report and exits
non-zero if any `live`/`frozen` entry is actually unreachable. It does NOT rewrite
entries — a human (or a future scheduled job) decides whether to flip a status to
`moved`/`dark`.

Uses curl for probes so wall-clock timeouts are reliable (urllib can hang past
socket timeouts on some federal hosts).

Usage:
    python scripts/check_links.py            # check all
    python scripts/check_links.py --json     # machine-readable report
    python scripts/check_links.py --timeout 10
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
DEFAULT_TIMEOUT = 12
UA = "ClimateAlmanac-link-checker/0.1 (+https://climatealmanac.com)"


def _probe(url: str, timeout: float) -> tuple[int | None, str]:
    """Return (http_status, note). None status = connection failed."""
    if not shutil.which("curl"):
        raise SystemExit("check_links.py requires curl on PATH")

    cmd = [
        "curl",
        "-sS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        str(int(timeout)),
        "-A",
        UA,
        "-L",
        url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timeout>{timeout + 5}s"

    if proc.returncode != 0 and not proc.stdout.strip().isdigit():
        err = (proc.stderr or proc.stdout or "curl failed").strip().splitlines()[-1]
        return None, err[:120]

    raw = proc.stdout.strip()
    if not raw.isdigit():
        return None, raw or "no status code"

    code = int(raw)
    return code, url


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SEC",
        help=f"per-request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    args = ap.parse_args()

    report = []
    problems = 0
    for path in sorted(CATALOG.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        url = entry.get("source", {}).get("canonical_url")
        declared = entry.get("status")
        code, note = _probe(url, args.timeout)
        reachable = code is not None and code < 400
        flagged = declared in ("live", "frozen") and not reachable
        if flagged:
            problems += 1
        report.append(
            {
                "id": entry.get("id"),
                "url": url,
                "declared_status": declared,
                "http": code,
                "reachable": reachable,
                "flagged": flagged,
                "note": note,
            }
        )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report:
            mark = "FLAG" if r["flagged"] else ("ok  " if r["reachable"] else "warn")
            print(f"[{mark}] {r['id']:34} status={r['declared_status']:8} http={r['http']}  {r['note']}")
        print(f"\n{problems} entr{'y' if problems == 1 else 'ies'} declared live/frozen but unreachable")

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
