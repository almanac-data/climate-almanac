#!/usr/bin/env python3
"""Archive capture job: keep a recent, dated copy of every live source.

For each `live` or `frozen` entry whose newest Wayback capture in `recovery[]` is
missing or older than `--max-age` days, it asks the Internet Archive's Save Page
Now to capture `source.canonical_url`, then records the resulting snapshot as a
`recovery[]` candidate:

    via: wayback, authenticity: timestamped, captured: <capture date>

When the entry carries a `fingerprint.sha256` baseline (a file artifact, not a
landing page), the capture's raw bytes are fetched and hashed. If they equal the
baseline, the candidate is `hash-verified` instead. That is the only route to the
top tier, and it is never assigned by fiat.

Read-only by default; prints what it would do. With `--write` it edits each
entry's `recovery` block and nothing else: `status`, `observed` and `fingerprint`
are never touched, and every edit is re-parsed to prove it. Candidates a person
recorded are always kept. At most `KEEP_MACHINE` captures this job made are kept
per entry (the newest), so the list doesn't grow without bound.

Polite by construction: at most `--limit` entries per run (oldest capture
first), and a pause between Save Page Now requests. Run it on a schedule (see
.github/workflows/capture-archives.yml) and every entry is reached over time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
MACHINE_NOTE = "Recorded by scripts/capture_archives.py"
KEEP_MACHINE = 3
RANK = {"hash-verified": 0, "cross-archive": 1, "timestamped": 2, "asserted": 3}
MONITORED = {"live", "frozen"}
# Save Page Now often takes minutes on a large page, and a request that times out
# here may still finish there; so wait longer, then look again before giving up.
SPN_TIMEOUT = 300
SETTLE_WAITS = (30, 60, 120)


def _user_agent() -> str:
    cfg = yaml.safe_load((ROOT / "almanac.config.yml").read_text()) or {}
    slug = cfg.get("slug") or "almanac"
    home = cfg.get("homepage") or ""
    return f"{slug}-archive-capture/0.1" + (f" (+{home})" if home else "")


def fetch(url: str, timeout: float = 90) -> tuple[int, bytes, str]:
    """GET a URL. Returns (status, body, final_url); status 0 on a network failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, b"", url
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b"", url


def newest_capture(url: str) -> str | None:
    """Timestamp (YYYYMMDDhhmmss) of the closest-to-now status-200 capture, or None."""
    q = "https://archive.org/wayback/available?" + urllib.parse.urlencode(
        {"url": url, "timestamp": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")})
    for attempt in range(3):
        code, body, _ = fetch(q, 60)
        if code == 200:
            snap = (json.loads(body or b"{}").get("archived_snapshots") or {}).get("closest") or {}
            ok = snap.get("available") and str(snap.get("status")) == "200"
            return snap.get("timestamp") if ok else None
        time.sleep(15 * (attempt + 1))
    return None


def save_page_now(url: str) -> int:
    """Ask Save Page Now for a fresh capture. Returns the HTTP status (0 = network failure)."""
    for attempt in range(3):
        code, _, _ = fetch("https://web.archive.org/save/" + url, SPN_TIMEOUT)
        if code != 429:
            return code
        time.sleep(60 * (attempt + 1))
    return 429


def _date(ts: str) -> str:
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def last_capture_date(entry: dict) -> str | None:
    dates = [r.get("captured") for r in entry.get("recovery") or []
             if r.get("via") == "wayback" and r.get("captured")]
    return max(str(d) for d in dates) if dates else None


def due(entry: dict, today: dt.date, max_age: int) -> bool:
    if entry.get("status") not in MONITORED or not (entry.get("source") or {}).get("canonical_url"):
        return False
    last = last_capture_date(entry)
    return last is None or dt.date.fromisoformat(last) < today - dt.timedelta(days=max_age)


def merge(recovery: list, url: str, candidate: dict) -> list:
    """Add a capture: drop asserted wayback wildcards for this URL and duplicates,
    keep every human-recorded candidate, keep the newest KEEP_MACHINE machine ones,
    and order by authenticity (never by who runs the copy)."""
    kept = [r for r in recovery or []
            if not (r.get("via") == "wayback" and r.get("authenticity") == "asserted"
                    and url.split("://", 1)[-1] in str(r.get("url")))
            and r.get("url") != candidate["url"]]
    machine = [r for r in kept if str(r.get("notes") or "").startswith(MACHINE_NOTE)]
    human = [r for r in kept if r not in machine]
    machine = sorted(machine + [candidate], key=lambda r: str(r.get("captured")), reverse=True)
    out = human + machine[:KEEP_MACHINE]
    return sorted(out, key=lambda r: RANK.get(r.get("authenticity"), 9))


def write_recovery(path: Path, recovery: list) -> None:
    """Replace the entry's top-level `recovery` block, changing nothing else."""
    text = path.read_text()
    before = yaml.safe_load(text)
    text = re.sub(r"^recovery:.*?(?=^[A-Za-z_]|\Z)", "", text, flags=re.M | re.S)
    block = yaml.safe_dump({"recovery": recovery}, sort_keys=False, allow_unicode=True, width=1000)
    m = re.search(r"^(coverage|license):", text, flags=re.M)
    text = text[:m.start()] + block + text[m.start():] if m else text.rstrip("\n") + "\n" + block
    after = yaml.safe_load(text)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if changed - {"recovery"}:
        raise RuntimeError(f"{path.name}: edit would change {sorted(changed)}")
    path.write_text(text)


def capture_one(entry: dict, today: dt.date) -> dict:
    """Request a capture for one entry and build its recovery candidate (or None)."""
    url = entry["source"]["canonical_url"]
    spn = save_page_now(url)
    ts = newest_capture(url)
    fresh_from = (today - dt.timedelta(days=1)).isoformat()
    if spn == 0 or 200 <= spn < 300:
        # timed out on our side, or accepted: the capture may still be landing
        for wait in SETTLE_WAITS:
            if ts and _date(ts) >= fresh_from:
                break
            time.sleep(wait)
            ts = newest_capture(url) or ts
    result = {"id": entry["id"], "url": url, "save_status": spn, "candidate": None}
    if not ts:
        result["note"] = "no capture available"
        return result
    last = last_capture_date(entry)
    if last and _date(ts) <= last:
        result["note"] = f"newest capture ({_date(ts)}) is no newer than the one recorded"
        return result
    snap = f"https://web.archive.org/web/{ts}/{url}"
    fresh = _date(ts) >= fresh_from
    auth = "timestamped"
    note = (f"{MACHINE_NOTE} on {today.isoformat()}: a capture it requested from Save Page Now."
            if fresh else
            f"{MACHINE_NOTE} on {today.isoformat()}: the newest existing capture "
            f"(Save Page Now returned {spn}).")
    baseline = (entry.get("fingerprint") or {}).get("sha256")
    if baseline:
        code, raw, _ = fetch(f"https://web.archive.org/web/{ts}id_/{url}", 180)
        if code == 200 and hashlib.sha256(raw).hexdigest() == baseline:
            auth = "hash-verified"
            note += " Its raw bytes match this entry's fingerprint.sha256 baseline."
    result["candidate"] = {"via": "wayback", "url": snap, "authenticity": auth,
                           "permission": "ok", "captured": _date(ts), "notes": note}
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-age", type=int, default=90,
                    help="re-capture when the newest Wayback capture is older than this many days")
    ap.add_argument("--limit", type=int, default=10, help="at most this many entries per run")
    ap.add_argument("--pause", type=float, default=20, help="seconds between Save Page Now requests")
    ap.add_argument("--write", action="store_true", help="record captures in recovery[]")
    ap.add_argument("--json", action="store_true", help="print a JSON report")
    args = ap.parse_args(argv)

    today = dt.date.today()
    entries = []
    for path in sorted(CATALOG.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        if due(entry, today, args.max_age):
            entries.append((last_capture_date(entry) or "", path, entry))
    entries.sort(key=lambda t: t[0])  # never-captured first, then oldest capture

    report = []
    for i, (_, path, entry) in enumerate(entries[: args.limit]):
        if i:
            time.sleep(args.pause)
        res = capture_one(entry, today)
        if res["candidate"] and args.write:
            write_recovery(path, merge(entry.get("recovery") or [], res["url"], res["candidate"]))
        report.append(res)
        if not args.json:
            c = res["candidate"]
            print(f"{res['id']}: save={res['save_status']} "
                  + (f"{c['authenticity']} {c['captured']}" if c else res.get("note", "")))
    if args.json:
        print(json.dumps({"due": len(entries), "attempted": len(report), "results": report}, indent=2))
    elif not entries:
        print("every live/frozen entry has a recent capture")
    return 0


if __name__ == "__main__":
    sys.exit(main())
