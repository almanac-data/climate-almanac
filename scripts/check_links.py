#!/usr/bin/env python3
"""Reachability checker — the seed of automated monitoring.

For each catalog entry, probes source.canonical_url and reports whether the
declared `status` still matches reality.

Read-only by default. With `--write-observed` it writes what it saw back into
each entry's `observed` block — the only thing in this repo permitted to do so,
because `observed` records machine facts and a hand-transcribed probe is not one.
It never touches `status`, `status_source`, or `status_since`: the machine
records facts, a human assigns the lifecycle label.

User-Agent is built from almanac.config.yml (slug + homepage) so agencies can see
who is checking. Three refinements keep the monitor from crying wolf at bot defenses:

  1. Browser-UA retry. A block code (401/403/406/429) triggers one retry with a
     common browser User-Agent — some hosts only sniff the UA.
  2. Headless fallback (opt-in). Many federal hosts (BLS, Census, Congress.gov,
     SEC, GAO) sit behind CDN bot protection (JS challenge + TLS fingerprinting)
     that no curl can satisfy — a 403 there is not a 404. When `--headless` is on
     (or `reachability.headless: true` in almanac.config.yml) a real headless
     Chromium is tried for blocked URLs; if it loads the page, the source is
     verified `ok via headless`. This needs Playwright (see requirements-headless.txt);
     if it is not installed the checker degrades gracefully to rung 3.
  3. Blocked != dead. If every rung still hits a block code, the source is
     reported as *blocked / unverifiable* — NOT flagged as an outage. The headless
     rung only ever *upgrades* a blocked source to ok; it never newly flags one as
     dead. Only genuine failures (404, 5xx, connection/timeout) flag an entry.

Uses curl for reliable wall-clock timeouts.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import shutil
import subprocess
import tempfile

from pathlib import Path
from urllib.parse import urljoin

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog"
CONFIG = ROOT / "almanac.config.yml"
DEFAULT_TIMEOUT = 12
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
BLOCK_CODES = {401, 403, 406, 429}


def _config() -> dict:
    if CONFIG.exists():
        return yaml.safe_load(CONFIG.read_text()) or {}
    return {}


def _user_agent() -> str:
    cfg = _config()
    slug = cfg.get("slug") or "almanac"
    homepage = cfg.get("homepage") or ""
    contact = f" (+{homepage})" if homepage else ""
    return f"{slug}-link-checker/0.1{contact}"


def _headless_default() -> bool:
    """Whether the headless fallback is enabled by config (CI reads the same flag)."""
    reach = _config().get("reachability") or {}
    return bool(reach.get("headless", False))


UA = _user_agent()


class Probe:
    """What a single probe actually saw. Facts only — no lifecycle interpretation.

    A plain class rather than a dataclass: this module is loaded via
    `importlib.util.module_from_spec` by the tests (and by anything else driving the
    scripts directly), and `@dataclass` resolving `from __future__` string annotations
    needs the module registered in `sys.modules`, which that loader does not do.
    """

    __slots__ = ("code", "note", "final_url", "redirect_chain")

    def __init__(self, code, note="", final_url=None, redirect_chain=None):
        self.code = code
        self.note = note
        self.final_url = final_url
        self.redirect_chain = redirect_chain if redirect_chain is not None else []

    def __iter__(self):
        """Legacy 2-tuple unpacking: `code, note = probe`."""
        return iter((self.code, self.note))

    def __repr__(self):
        return (f"Probe(code={self.code!r}, note={self.note!r}, "
                f"final_url={self.final_url!r}, redirect_chain={self.redirect_chain!r})")


def _redirect_chain(header_dump: str, start_url: str) -> list[str]:
    """Ordered hops from the Location headers of a followed redirect chain.

    Relative Locations are resolved against the URL that produced them, so the
    chain is absolute URLs throughout — which is what `observed.redirect_chain`
    is specified to hold.
    """
    chain: list[str] = []
    current = start_url
    for line in header_dump.splitlines():
        if line.lower().startswith("location:"):
            target = line.split(":", 1)[1].strip()
            if not target:
                continue
            current = urljoin(current, target)
            chain.append(current)
    return chain


def _curl(url: str, timeout: float, ua: str) -> Probe:
    with tempfile.NamedTemporaryFile("w+", suffix=".hdr", delete=True) as hdr:
        cmd = ["curl", "-sS", "-o", "/dev/null", "-D", hdr.name,
               "-w", "%{http_code}\t%{url_effective}",
               "--max-time", str(int(timeout)), "-A", ua, "-L", url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout + 5, check=False)
        except subprocess.TimeoutExpired:
            return Probe(None, f"timeout>{timeout + 5}s")
        raw = proc.stdout.strip()
        code_part, _, final_url = raw.partition("\t")
        code_part = code_part.strip()
        if proc.returncode != 0 and not code_part.isdigit():
            err = (proc.stderr or proc.stdout or "curl failed").strip().splitlines()[-1]
            return Probe(None, err[:120])
        if not code_part.isdigit():
            return Probe(None, raw or "no status code")
        code = int(code_part)
        if code == 0:
            # curl prints "000" when it never got an HTTP response at all — DNS
            # failure, connection refused, TLS failure, timeout. It is a digit, so
            # it parses; treating it as a status makes `0 < 400` true and reports a
            # source that has entirely vanished as reachable. That is the one
            # outage this monitor exists to catch, so it must be "no response".
            err = (proc.stderr or "").strip().splitlines()
            return Probe(None, f"no response ({err[-1][:80]})" if err else "no response")
        hdr.seek(0)
        chain = _redirect_chain(hdr.read(), url)
    return Probe(code, "", final_url.strip() or url, chain)


def _probe_headless(url: str, timeout: float) -> tuple[int | None, str]:
    """Load the URL in a real headless Chromium — beats JS/TLS bot challenges curl can't.

    Returns (status, note). status is None when the headless rung could not run
    (Playwright missing) or could not reach the page; callers must treat a None or
    non-2xx/3xx result as *still blocked*, never as a dead-link flag.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright not installed (see requirements-headless.txt)"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=BROWSER_UA)
                resp = page.goto(url, wait_until="domcontentloaded",
                                 timeout=int(timeout * 1000))
                return (resp.status if resp else None), ""
            finally:
                browser.close()
    except Exception as exc:  # navigation timeout, challenge wall, launch failure
        return None, f"headless {type(exc).__name__}"


def _probe(url: str, timeout: float, headless: bool = False) -> Probe:
    """Probe with the almanac UA; retry as a browser, then (opt-in) as headless Chromium."""
    if not shutil.which("curl"):
        raise SystemExit("check_links.py requires curl on PATH")
    first = _curl(url, timeout, UA)
    if first.code in BLOCK_CODES:
        browser = _curl(url, timeout, BROWSER_UA)
        if browser.code is not None and browser.code < 400:
            browser.note = f"ok via browser-UA (almanac-UA got {first.code})"
            return browser
        best = browser if browser.code is not None else first
        c = best.code
        if c in BLOCK_CODES:
            # curl can't beat CDN bot protection; try a real headless browser.
            if headless:
                hcode, hnote = _probe_headless(url, timeout)
                if hcode is not None and hcode < 400:
                    # Headless reached it, but only curl reports the redirect chain,
                    # so record the status without inventing hops we did not observe.
                    return Probe(hcode, f"ok via headless (curl got {c})", url, [])
                detail = f"; {hnote}" if hnote else ""
                best.note = f"blocked by bot protection ({c}) — headless unverified{detail}"
                return best
            best.note = f"blocked by bot protection ({c}) — cannot auto-verify"
            return best
        best.note = best.note or f"http {c}"
        return best
    return first


def _body_sha256(url: str, timeout: float, ua: str, max_bytes: int = 100_000_000) -> str | None:
    """Hash the fetched artifact. Returns None when it could not be fetched whole.

    Only called for entries that already carry a `fingerprint.sha256` baseline, so
    the cost of downloading a body is paid only where there is something to compare
    against. A truncated download is never hashed — a partial hash would compare
    unequal and manufacture a false `drift`.
    """
    with tempfile.NamedTemporaryFile(suffix=".body", delete=True) as body:
        cmd = ["curl", "-sS", "-o", body.name, "--max-filesize", str(max_bytes),
               "--max-time", str(int(timeout)), "-A", ua, "-L", url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout + 5, check=False)
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:  # includes 63 = --max-filesize exceeded
            return None
        return hashlib.sha256(Path(body.name).read_bytes()).hexdigest()


def _fingerprint_result(entry: dict, probe: Probe, timeout: float) -> str | None:
    """Compare the live artifact against the stored baseline.

    Returns None to mean "not observed" — the caller then leaves whatever value is
    already on the entry alone. Absent a baseline there is nothing to compare and
    the honest answer is `no-baseline`, not a manufactured `match`.
    """
    baseline = ((entry.get("fingerprint") or {}).get("sha256"))
    if not baseline:
        return "no-baseline"
    if probe.code is None or probe.code >= 400:
        return None
    digest = _body_sha256(entry["source"]["canonical_url"], timeout, UA)
    if digest is None:
        return None
    return "match" if digest == baseline else "drift"


def _scalar(key: str, value) -> str:
    """One `key: value` line, quoted exactly as PyYAML would quote it."""
    return yaml.safe_dump({key: value}, default_flow_style=False,
                          sort_keys=False, allow_unicode=True).strip()


def render_observed(observed: dict, indent: str = "  ") -> str:
    """Render an `observed` block in the catalog's hand-written YAML style.

    Written as text rather than dumped as YAML on purpose: round-tripping a whole
    entry through PyYAML reflows every block scalar and re-quotes every string,
    which would churn files this change has no business touching.
    """
    lines = ["observed:"]
    for key in ("checked", "reachable", "http_status", "final_url"):
        lines.append(indent + _scalar(key, observed.get(key)))
    chain = observed.get("redirect_chain") or []
    if chain:
        lines.append(indent + "redirect_chain:")
        rendered = yaml.safe_dump(chain, default_flow_style=False,
                                  sort_keys=False, allow_unicode=True).strip()
        lines.extend(indent + item for item in rendered.splitlines())
    else:
        lines.append(indent + "redirect_chain: []")
    lines.append(indent + _scalar("fingerprint_result", observed.get("fingerprint_result")))
    return "\n".join(lines)


def replace_observed_block(text: str, block: str) -> str | None:
    """Swap an entry's `observed:` block for `block`, leaving the rest byte-identical.

    Returns None when the file has no `observed:` block — the schema requires one,
    so that is a malformed entry to report rather than a file to guess at.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "observed:")
    except StopIteration:
        return None
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        if not lines[end].strip() and end + 1 < len(lines) and not lines[end + 1].startswith((" ", "\t")):
            break  # blank line separating top-level keys belongs to what follows
        end += 1
    trailing = "\n" if text.endswith("\n") else ""
    return "\n".join(lines[:start] + block.splitlines() + lines[end:]) + trailing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="SEC",
                    help=f"per-request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    ap.add_argument("--headless", action=argparse.BooleanOptionalAction,
                    default=_headless_default(),
                    help="verify CDN-bot-blocked sources with a headless browser "
                         "(needs Playwright; defaults to reachability.headless in config)")
    ap.add_argument("--write-observed", action="store_true",
                    help="write the probe's facts back into each entry's `observed` block "
                         "(status is never touched). Re-run build_index.py afterwards.")
    args = ap.parse_args()

    today = _dt.date.today().isoformat()
    report = []
    problems = 0
    written = 0
    for path in sorted(CATALOG.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text())
        url = entry.get("source", {}).get("canonical_url")
        declared = entry.get("status")
        probe = _probe(url, args.timeout, headless=args.headless)
        code, note = probe.code, probe.note
        blocked = code in BLOCK_CODES
        reachable = code is not None and code < 400
        # Dead = a definitive failure (404 / 5xx / connection / timeout).
        # A host that merely blocks our bot is unverifiable, not dead.
        dead = (not reachable) and (not blocked)
        flagged = declared in ("live", "frozen") and dead
        if flagged:
            problems += 1
        report.append({"id": entry.get("id"), "url": url, "declared_status": declared,
                       "http": code, "reachable": reachable, "blocked": blocked,
                       "flagged": flagged, "note": note,
                       "final_url": probe.final_url, "redirect_chain": probe.redirect_chain})

        if args.write_observed:
            observed = dict(entry.get("observed") or {})
            fp = _fingerprint_result(entry, probe, args.timeout)
            observed.update({
                "checked": today,
                # The schema defines observed.reachable as "did the probe get any
                # response?" — NOT "did it succeed". A bot-blocked 403 is a response,
                # so it records reachable: true with http_status: 403. Collapsing those
                # into false would relabel `blocked` as `dead`, which rung 3 exists to
                # prevent. The local `reachable` below is the stricter <400 notion used
                # only to decide whether a declared status looks wrong.
                "reachable": code is not None,
                "http_status": code,
                "final_url": probe.final_url,
                "redirect_chain": probe.redirect_chain,
            })
            if fp is not None:
                observed["fingerprint_result"] = fp
            updated = replace_observed_block(path.read_text(), render_observed(observed))
            if updated is None:
                print(f"  ! {path.name}: no `observed:` block to write — skipped")
            elif updated != path.read_text():
                path.write_text(updated)
                written += 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report:
            mark = "FLAG" if r["flagged"] else ("blok" if r["blocked"] else ("ok  " if r["reachable"] else "warn"))
            print(f"[{mark}] {r['id']:34} status={r['declared_status']:8} http={r['http']}  {r['note']}")
        print(f"\n{problems} entr{'y' if problems == 1 else 'ies'} declared live/frozen but unreachable")
    if args.write_observed:
        print(f"wrote `observed` into {written} entr{'y' if written == 1 else 'ies'}"
              " — run scripts/build_index.py to refresh catalog.json")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
