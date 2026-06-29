#!/usr/bin/env python3
"""Validate every catalog/*.yaml entry against schema/catalog-entry.schema.json.

Also enforces: filename stem == entry id, and ids are unique.
Exit non-zero on any failure (CI gate).
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "catalog-entry.schema.json"
CATALOG = ROOT / "catalog"


def _stringify_dates(obj):
    """YAML parses bare ISO dates (2026-06-28) into date objects; the schema
    wants strings. Normalize date/datetime to ISO strings so contributors can
    write dates with or without quotes without tripping validation."""
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    return obj


def main() -> int:
    schema = json.loads(SCHEMA.read_text())
    validator = Draft202012Validator(schema)

    errors: list[str] = []
    seen_ids: dict[str, str] = {}

    files = sorted(CATALOG.glob("*.yaml"))
    if not files:
        print("no catalog entries found", file=sys.stderr)
        return 1

    for path in files:
        entry = _stringify_dates(yaml.safe_load(path.read_text()))
        stem = path.stem

        for err in sorted(validator.iter_errors(entry), key=lambda e: list(e.path)):
            loc = ".".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{path.name}: {loc}: {err.message}")

        entry_id = entry.get("id") if isinstance(entry, dict) else None
        if entry_id and entry_id != stem:
            errors.append(f"{path.name}: id '{entry_id}' != filename stem '{stem}'")
        if entry_id in seen_ids:
            errors.append(f"{path.name}: duplicate id '{entry_id}' (also in {seen_ids[entry_id]})")
        elif entry_id:
            seen_ids[entry_id] = path.name

    if errors:
        print(f"FAIL — {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"OK — {len(files)} entr{'y' if len(files) == 1 else 'ies'} valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
