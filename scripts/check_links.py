#!/usr/bin/env python3
"""Reachability checker — the seed of automated monitoring.

For each catalog entry, HEAD (falling back to GET) its source.canonical_url and
report whether the declared `status` still matches reality. Read-only: it prints
a report and exits non-zero if any `live`/`frozen` entry is actually unreachable.
It does NOT rewrite entries — a human (or a future scheduled job) decides whether
to flip a status to `moved`/`dark`.

Usage:
    python scripts/check_links.py            # check all
    python scripts/check_links.py --json     # machine-readable report
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
TIMEOUT = 15
UA = "ClimateAlmanac-link-checker/0.1 (+https://climatealmanac.com)"


def _probe(url: str) -> tuple[int | None, str]:
    """Return (http_status, note). None status = connection failed."""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.geturl()
        except urllib.error.HTTPError as e:
            # Some servers reject HEAD with 405 — retry with GET before giving up.
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return e.code, str(e.reason)
        except Exception as e:  # noqa: BLE001 - report any connection failure
            if method == "HEAD":
                continue
            return None, f"{type(e).__name__}: {e}"
    return None, "unreachable"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    report = []
    problems = 0
    for path in sorted(CATALOG.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        url = entry.get("source", {}).get("canonical_url")
        declared = entry.get("status")
        code, note = _probe(url)
        reachable = code is not None and code < 400
        # A 'live' or 'frozen' entry that we can't reach is a real problem.
        flagged = declared in ("live", "frozen") and not reachable
        if flagged:
            problems += 1
        report.append(
            {
                "id": entry.get("id"),
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
