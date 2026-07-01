#!/usr/bin/env python3
"""Build catalog.json from every catalog/*.yaml entry.

Deterministic output (sorted by id) so diffs stay clean. The index name and
description come from almanac.config.yml so this engine stays domain-agnostic.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
CONFIG = ROOT / "almanac.config.yml"
OUT = ROOT / "catalog.json"


def _stringify_dates(obj):
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def _config() -> dict:
    if CONFIG.exists():
        return yaml.safe_load(CONFIG.read_text()) or {}
    return {}


def main() -> int:
    cfg = _config()
    entries = [
        _stringify_dates(yaml.safe_load(p.read_text()))
        for p in sorted(CATALOG.glob("*.yaml"))
    ]
    entries.sort(key=lambda e: e.get("id", ""))

    index = {
        "name": cfg.get("name", "Almanac"),
        "description": cfg.get("description", "An open, versioned index of public data."),
        "count": len(entries),
        "by_status": _counts(entries, "status"),
        "entries": entries,
    }
    OUT.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.name} — {len(entries)} entries ({index['by_status']})")
    return 0


def _counts(entries, field):
    out: dict[str, int] = {}
    for e in entries:
        out[e.get(field, "unknown")] = out.get(e.get(field, "unknown"), 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    raise SystemExit(main())
