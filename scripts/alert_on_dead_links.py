#!/usr/bin/env python3
"""Turn a reachability report into GitHub issues — the audible half of the alarm.

`check_links.py` is read-only: it probes canonical URLs and prints a report. This
script consumes that report (`check_links.py --json`) and reconciles GitHub issues
so a dead endpoint becomes an actionable, labelled issue instead of a red X on a
hidden dashboard.

Design:
  * Idempotent by *marker*, not by run. Every issue this script opens carries a
    hidden HTML marker (`<!-- almanac-alert:id=... -->` or `domain=...`). Each run
    computes the desired set and reconciles against open issues — so the daily cron
    never spams duplicates.
  * Circuit breaker. If more than --domain-threshold flagged entries share one host
    (e.g. an agency rotates its base URL and 9 datasets fail at once), suppress the
    individual issues and open ONE agency-level `[outage]` issue with a task list and
    an embedded JSON manifest for scraping tools.
  * Auto-close on recovery. An open automated issue whose endpoint is reachable again
    is closed with a dated comment. The alarm resets itself.

Read-only by default-ish: pass --dry-run to print the plan without touching GitHub.

Auth: uses GITHUB_TOKEN and GITHUB_REPOSITORY (both provided by GitHub Actions).

Usage:
    python scripts/check_links.py --json | python scripts/alert_on_dead_links.py
    python scripts/alert_on_dead_links.py --report link-check-report.json --dry-run
    python scripts/alert_on_dead_links.py --report r.json --domain-threshold 5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import timezone, datetime
from urllib.parse import urlparse

API = "https://api.github.com"
MARKER_PREFIX = "almanac-alert"
LABELS = {
    "endpoint-dead": ("b60205", "A catalogued source is unreachable (declared live/frozen)."),
    "automated": ("ededed", "Opened automatically by a workflow."),
    "outage": ("d93f0b", "Multiple datasets from one host are down at once."),
    "needs-curation": ("0e8a16", "A human should update the affected catalog entry."),
}


def _marker(kind: str, value: str) -> str:
    return f"<!-- {MARKER_PREFIX}:{kind}={value} -->"


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


class GitHub:
    def __init__(self, repo: str, token: str, dry_run: bool):
        self.repo = repo
        self.token = token
        self.dry_run = dry_run

    def _req(self, method: str, path: str, body: dict | None = None) -> object:
        url = path if path.startswith("http") else f"{API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}

    def ensure_labels(self) -> None:
        if self.dry_run:
            return
        for name, (color, desc) in LABELS.items():
            try:
                self._req("POST", f"/repos/{self.repo}/labels",
                          {"name": name, "color": color, "description": desc})
            except urllib.error.HTTPError as e:
                if e.code != 422:  # 422 = already exists
                    raise

    def open_automated_issues(self) -> list[dict]:
        """All open issues carrying the endpoint-dead label (paginated).

        Returns [] when no token/repo is configured (offline --dry-run planning),
        so a local dry run shows the create plan without hitting the network.
        """
        if not (self.repo and self.token):
            return []
        out: list[dict] = []
        page = 1
        while True:
            q = urllib.parse.urlencode(
                {"state": "open", "labels": "endpoint-dead", "per_page": 100, "page": page}
            )
            batch = self._req("GET", f"/repos/{self.repo}/issues?{q}")
            if not isinstance(batch, list) or not batch:
                break
            out.extend(i for i in batch if "pull_request" not in i)
            if len(batch) < 100:
                break
            page += 1
        return out

    def create_issue(self, title: str, body: str, labels: list[str]) -> None:
        if self.dry_run:
            print(f"[dry-run] CREATE {title!r} labels={labels}")
            return
        self._req("POST", f"/repos/{self.repo}/issues",
                  {"title": title, "body": body, "labels": labels})

    def update_issue_body(self, number: int, body: str) -> None:
        if self.dry_run:
            print(f"[dry-run] UPDATE #{number} body")
            return
        self._req("PATCH", f"/repos/{self.repo}/issues/{number}", {"body": body})

    def close_issue(self, number: int, comment: str) -> None:
        if self.dry_run:
            print(f"[dry-run] CLOSE #{number} — {comment}")
            return
        self._req("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": comment})
        self._req("PATCH", f"/repos/{self.repo}/issues/{number}", {"state": "closed"})


def _find(issues: list[dict], marker: str) -> dict | None:
    return next((i for i in issues if marker in (i.get("body") or "")), None)


def _entry_issue_body(r: dict, today: str) -> str:
    return (
        f"{_marker('id', r['id'])}\n\n"
        f"The catalogued source for **`{r['id']}`** is declared "
        f"`{r['declared_status']}` but was unreachable on {today}.\n\n"
        f"- **URL:** {r['url']}\n"
        f"- **HTTP:** {r['http']}\n"
        f"- **Probe note:** {r['note']}\n\n"
        "### What to do\n"
        f"Verify the source, then update `catalog/{r['id']}.yaml`:\n"
        "- If it moved, set `status: moved` and update `source.canonical_url`.\n"
        "- If it is gone, set `status: dark`, add a `notes` line and "
        "`archive.wayback_url`.\n"
        "- If it is a transient blip, no change — this issue auto-closes when the "
        "probe succeeds again.\n\n"
        "_Opened automatically from the daily reachability probe "
        "(`scripts/check_links.py`)._"
    )


def _outage_issue_body(host: str, group: list[dict], today: str) -> str:
    tasks = "\n".join(
        f"- [ ] `{r['id']}` — {r['url']} (HTTP {r['http']}, {r['note']})" for r in group
    )
    manifest = json.dumps(
        {
            "host": host,
            "detected": today,
            "count": len(group),
            "datasets": [
                {"id": r["id"], "url": r["url"], "http": r["http"],
                 "declared_status": r["declared_status"]}
                for r in group
            ],
        },
        indent=2,
    )
    return (
        f"{_marker('domain', host)}\n\n"
        f"**{len(group)} datasets** hosted on `{host}` were unreachable on {today}. "
        "This usually means an agency changed its base URL or had an outage — handle "
        "the host once rather than chasing each dataset.\n\n"
        "### Affected datasets\n"
        f"{tasks}\n\n"
        "### Machine-readable manifest\n"
        "For scraping / triage tools:\n\n"
        f"```json\n{manifest}\n```\n\n"
        "Individual per-dataset alerts for this host are suppressed while this "
        "outage issue is open. It auto-closes when every dataset above is reachable "
        "again.\n\n"
        "_Opened automatically from the daily reachability probe "
        "(`scripts/check_links.py`)._"
    )


def reconcile(report: list[dict], gh: GitHub, threshold: int) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    flagged = [r for r in report if r.get("flagged")]
    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in flagged:
        by_host[_host(r["url"])].append(r)

    outage_hosts = {h for h, g in by_host.items() if len(g) >= threshold}
    # ids that are covered by an outage issue (their individual alert is suppressed)
    suppressed_ids = {r["id"] for h in outage_hosts for r in by_host[h]}
    individual = [r for r in flagged if r["id"] not in suppressed_ids]

    reachable_now = {r["id"]: r for r in report if r.get("reachable")}
    open_issues = gh.open_automated_issues()
    gh.ensure_labels()

    # 1. agency-level outage issues
    for host in sorted(outage_hosts):
        group = sorted(by_host[host], key=lambda r: r["id"])
        body = _outage_issue_body(host, group, today)
        existing = _find(open_issues, _marker("domain", host))
        if existing:
            gh.update_issue_body(existing["number"], body)
            print(f"refreshed outage issue #{existing['number']} for {host} ({len(group)})")
        else:
            gh.create_issue(
                f"[outage] {host} — {len(group)} datasets unreachable",
                body,
                ["endpoint-dead", "outage", "automated", "needs-curation"],
            )
            print(f"opened outage issue for {host} ({len(group)})")

    # 2. individual issues
    for r in sorted(individual, key=lambda r: r["id"]):
        if _find(open_issues, _marker("id", r["id"])):
            print(f"already tracking {r['id']}")
            continue
        gh.create_issue(
            f"[endpoint-dead] {r['id']} unreachable",
            _entry_issue_body(r, today),
            ["endpoint-dead", "automated", "needs-curation"],
        )
        print(f"opened issue for {r['id']}")

    # 3. auto-close recovered / superseded issues
    for issue in open_issues:
        body = issue.get("body") or ""
        for kind, value in (("id", None), ("domain", None)):
            tag = f"{MARKER_PREFIX}:{kind}="
            if tag not in body:
                continue
            value = body.split(tag, 1)[1].split(" ", 1)[0].strip()
            if kind == "id":
                rec = reachable_now.get(value)
                still_flagged = any(r["id"] == value for r in flagged)
                if rec and not still_flagged:
                    gh.close_issue(
                        issue["number"],
                        f"Reachable again as of {today} (HTTP {rec['http']}). "
                        "Closing automatically.",
                    )
                    print(f"closed recovered issue #{issue['number']} ({value})")
                elif value in suppressed_ids:
                    gh.close_issue(
                        issue["number"],
                        f"Superseded by the host-level outage issue for `{_host(rec['url']) if rec else value}` "
                        f"as of {today}. Closing automatically.",
                    )
                    print(f"closed superseded issue #{issue['number']} ({value})")
            else:  # domain
                if value not in outage_hosts:
                    gh.close_issue(
                        issue["number"],
                        f"All datasets on `{value}` are reachable again (or below the "
                        f"outage threshold) as of {today}. Closing automatically.",
                    )
                    print(f"closed recovered outage issue #{issue['number']} ({value})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", help="path to check_links.py --json output (default: stdin)")
    ap.add_argument("--domain-threshold", type=int, default=5,
                    help="flagged entries on one host before consolidating into a single "
                         "outage issue (default: 5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan; do not touch GitHub")
    args = ap.parse_args()

    raw = open(args.report).read() if args.report else sys.stdin.read()
    report = json.loads(raw)
    if not isinstance(report, list):
        raise SystemExit("expected a JSON list from check_links.py --json")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not args.dry_run and not (repo and token):
        raise SystemExit("GITHUB_REPOSITORY and GITHUB_TOKEN are required (or use --dry-run)")

    gh = GitHub(repo, token, args.dry_run)
    reconcile(report, gh, args.domain_threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
