#!/usr/bin/env python3
"""Migrate catalog/*.yaml entries from schema v1 to v2 (see SCHEMA-V2.md).

Mechanical field mapping only — see the table in SCHEMA-V2.md for the full
rationale. Entries that already look like v2 (have both `type` and `observed`)
are left untouched. Never auto-promotes authenticity tiers or invents facts
(rule 2/5 of the Constitution): anything the script can't map with confidence
is carried over as an honest low tier (`asserted`) and flagged in `notes` for
curator review rather than guessed.

Usage:
  python scripts/migrate_v1_v2.py --dry-run   # show what would change (default)
  python scripts/migrate_v1_v2.py --apply     # rewrite files in place

After --apply: run scripts/validate.py, review every "NEEDS REVIEW" note by
hand, then commit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"


def _str_presenter(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _str_presenter)


def is_v2(entry: dict) -> bool:
    return "type" in entry and "observed" in entry


def migrate_entry(entry: dict) -> tuple[dict, list[str]]:
    """Return (v2_entry, review_notes). review_notes is empty for a clean, confident mapping."""
    review: list[str] = []
    out: dict = {}

    out["id"] = entry["id"]
    out["type"] = "dataset"
    out["title"] = entry["title"]
    out["description"] = entry["description"]
    out["publisher"] = entry["publisher"]
    out["topics"] = entry["topics"]

    src = entry.get("source") or {}
    new_source = {"canonical_url": src.get("canonical_url")}
    if src.get("doi"):
        new_source["identifiers"] = {"doi": src["doi"]}
    out["source"] = new_source

    out["access"] = entry.get("access") or {}

    if entry.get("format"):
        out["format"] = entry["format"]

    recovery = []
    if src.get("predecessor_url"):
        recovery.append({
            "via": "predecessor",
            "url": src["predecessor_url"],
            "authenticity": "asserted",
            "permission": "ok",
        })

    archive = entry.get("archive") or {}
    if archive.get("wayback_url"):
        recovery.append({
            "via": "wayback",
            "url": archive["wayback_url"],
            "authenticity": "asserted",
            "permission": "ok",
        })
    if archive.get("cloud_mirror"):
        recovery.append({
            "via": "cloud_mirror",
            "url": archive["cloud_mirror"],
            "authenticity": "asserted",
            "permission": "ok",
        })
    if archive.get("mirror"):
        recovery.append({
            "via": "self",
            "url": archive["mirror"],
            "authenticity": "hash-verified" if entry.get("checksum") else "asserted",
            "permission": "ok",
        })
    if recovery:
        out["recovery"] = recovery

    status = entry.get("status", "live")
    if status == "mirrored":
        review.append(
            "status was 'mirrored' (v1) — no direct v2 equivalent; set to 'dark' here "
            "with a `self` recovery candidate. Confirm the correct v2 lifecycle status."
        )
        status = "dark"
    out["status"] = status
    if entry.get("last_checked"):
        out["status_since"] = entry["last_checked"]
    out["status_source"] = "auto"

    checksum = entry.get("checksum")
    if checksum:
        out["fingerprint"] = {
            "sha256": checksum,
            "etag": None,
            "content_length": None,
            "captured": entry.get("last_checked"),
            "algo": "sha256",
        }
        review.append(
            "v1 `checksum` carried into `fingerprint.sha256` as a baseline — confirm it "
            "was actually captured while the resource was live, not just a mirror hash."
        )

    out["observed"] = {
        "checked": entry.get("last_checked"),
        "reachable": None,
        "http_status": None,
        "final_url": None,
        "redirect_chain": [],
        "fingerprint_result": "no-baseline",
    }

    if entry.get("coverage"):
        out["coverage"] = entry["coverage"]

    out["license"] = entry.get("license")
    out["attribution"] = entry.get("attribution")

    notes = entry.get("notes")
    if review:
        review_block = "MIGRATION REVIEW (v1->v2): " + " ".join(review)
        notes = f"{notes.strip()}\n{review_block}" if notes else review_block
    out["notes"] = notes

    return out, review


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    if not apply and "--dry-run" not in sys.argv[1:] and len(sys.argv) > 1:
        print(f"Unknown option: {sys.argv[1]}", file=sys.stderr)
        return 2

    files = sorted(CATALOG.glob("*.yaml"))
    if not files:
        print("no catalog entries found", file=sys.stderr)
        return 1

    migrated = 0
    flagged = 0
    for path in files:
        entry = yaml.safe_load(path.read_text())
        if is_v2(entry):
            print(f"  = {path.name} (already v2)")
            continue

        v2_entry, review = migrate_entry(entry)
        migrated += 1
        marker = "~" if not apply else "+"
        print(f"  {marker} {path.name}" + (" [NEEDS REVIEW]" if review else ""))
        for note in review:
            flagged += 1
            print(f"      - {note}")

        if apply:
            path.write_text(yaml.dump(v2_entry, sort_keys=False, allow_unicode=True, width=100))

    if not files:
        return 1

    if apply:
        print(f"\nApplied — {migrated} entr{'y' if migrated == 1 else 'ies'} migrated, {flagged} flagged for review.")
        print("Next: python scripts/validate.py, then review every NEEDS REVIEW note by hand.")
    else:
        print(f"\nDry run only — {migrated} entr{'y' if migrated == 1 else 'ies'} would migrate, {flagged} would be flagged.")
        print("Re-run with --apply to write files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
