import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_migrator():
    spec = importlib.util.spec_from_file_location("mv", ROOT / "scripts" / "migrate_v1_v2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_validate_passes():
    r = subprocess.run([sys.executable, "scripts/validate.py"], cwd=ROOT)
    assert r.returncode == 0


def test_build_index_sorted_and_unique():
    subprocess.run([sys.executable, "scripts/build_index.py"], cwd=ROOT, check=True)
    data = json.loads((ROOT / "catalog.json").read_text())
    assert data["count"] == len(data["entries"])
    ids = [e["id"] for e in data["entries"]]
    assert ids == sorted(ids), "entries must be sorted by id"
    assert len(ids) == len(set(ids)), "ids must be unique"


def test_schema_is_well_formed():
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "schema" / "catalog-entry.schema.json").read_text())
    Draft202012Validator.check_schema(schema)


def _load_checker():
    spec = importlib.util.spec_from_file_location("cl", ROOT / "scripts" / "check_links.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_checker_classifies_bot_blocks():
    mod = _load_checker()
    # Block codes are treated as "unverifiable", never as a dead-link flag.
    assert {401, 403, 406, 429} <= mod.BLOCK_CODES


def test_probe_blocked_without_headless_stays_unverifiable(monkeypatch):
    mod = _load_checker()
    # Both curl rungs blocked; headless off -> blocked code, not a dead flag.
    monkeypatch.setattr(mod, "_curl", lambda url, t, ua: mod.Probe(403, ""))
    code, note = mod._probe("https://bls.gov", 5, headless=False)
    assert code == 403 and "cannot auto-verify" in note


def test_probe_headless_upgrades_block_to_ok(monkeypatch):
    mod = _load_checker()
    monkeypatch.setattr(mod, "_curl", lambda url, t, ua: mod.Probe(403, ""))
    monkeypatch.setattr(mod, "_probe_headless", lambda url, t: (200, ""))
    code, note = mod._probe("https://bls.gov", 5, headless=True)
    assert code == 200 and "headless" in note


def test_probe_headless_failure_never_flags_dead(monkeypatch):
    mod = _load_checker()
    # Headless rung can't run / can't reach -> stay blocked, never report dead.
    monkeypatch.setattr(mod, "_curl", lambda url, t, ua: mod.Probe(403, ""))
    monkeypatch.setattr(mod, "_probe_headless", lambda url, t: (None, "playwright not installed"))
    code, note = mod._probe("https://bls.gov", 5, headless=True)
    assert code == 403  # block code preserved
    assert code in mod.BLOCK_CODES  # classified blocked, not dead, downstream


def _v1_entry(**overrides):
    base = {
        "id": "example",
        "title": "Example",
        "description": "A dataset used only to exercise the v1->v2 migrator.",
        "publisher": "Example Agency",
        "topics": ["example"],
        "source": {"canonical_url": "https://example.org", "predecessor_url": None, "doi": None},
        "access": {"method": ["web"], "auth_required": False, "auth_note": None, "rate_limit": None},
        "format": ["csv"],
        "coverage": {"spatial": "global", "temporal": "n/a", "cadence": "static"},
        "license": "CC0-1.0",
        "attribution": "Example Agency",
        "archive": {"wayback_url": None, "cloud_mirror": None, "mirror": None},
        "status": "live",
        "last_checked": "2026-07-01",
        "checksum": None,
        "notes": None,
    }
    base.update(overrides)
    return base


def test_migrate_is_schema_valid_and_flags_nothing_on_the_clean_path():
    from jsonschema import Draft202012Validator
    mod = _load_migrator()
    schema = json.loads((ROOT / "schema" / "catalog-entry.schema.json").read_text())
    v2_entry, review = mod.migrate_entry(_v1_entry())
    assert review == []
    Draft202012Validator(schema).validate(v2_entry)


def test_migrate_flags_mirrored_status_and_checksum_for_review():
    mod = _load_migrator()
    v2_entry, review = mod.migrate_entry(_v1_entry(status="mirrored", checksum="abc123"))
    assert v2_entry["status"] == "dark"  # no direct v2 equivalent for 'mirrored'
    assert v2_entry["fingerprint"]["sha256"] == "abc123"
    assert len(review) == 2  # both the status collapse and the checksum carry-over need a human look


def test_migrate_is_idempotent():
    mod = _load_migrator()
    assert mod.is_v2({"type": "dataset", "observed": {"checked": "2026-07-01"}}) is True
    assert mod.is_v2(_v1_entry()) is False


# --- observed writer (check_links.py --write-observed) ---------------------------

SAMPLE_ENTRY = """id: sample
type: dataset
title: Sample
description: |
  A multi-line block scalar that must survive untouched.
status: live
status_since: '2026-01-01'
status_source: curator
observed:
  checked: '2026-01-01'
  reachable: null
  http_status: null
  final_url: null
  redirect_chain: []
  fingerprint_result: no-baseline
license: CC0-1.0
notes: |
  Trailing block scalar.
"""


def test_redirect_chain_resolves_relative_locations():
    mod = _load_checker()
    headers = "HTTP/1.1 301\r\nLocation: /moved\r\n\r\nHTTP/1.1 302\r\nLocation: https://elsewhere.gov/x\r\n"
    assert mod._redirect_chain(headers, "https://agency.gov/start") == [
        "https://agency.gov/moved",
        "https://elsewhere.gov/x",
    ]


def test_render_observed_is_yaml_and_keeps_nulls_explicit():
    mod = _load_checker()
    import yaml as _y
    block = mod.render_observed({"checked": "2026-08-04", "reachable": None, "http_status": None,
                                 "final_url": None, "redirect_chain": [],
                                 "fingerprint_result": "no-baseline"})
    parsed = _y.safe_load(block)["observed"]
    assert parsed["reachable"] is None and parsed["redirect_chain"] == []
    assert "redirect_chain: []" in block  # empty chain stays inline, as hand-written entries have it


def test_render_observed_emits_a_populated_redirect_chain():
    mod = _load_checker()
    import yaml as _y
    block = mod.render_observed({"checked": "2026-08-04", "reachable": True, "http_status": 200,
                                 "final_url": "https://agency.gov/final",
                                 "redirect_chain": ["https://agency.gov/a", "https://agency.gov/final"],
                                 "fingerprint_result": "no-baseline"})
    parsed = _y.safe_load(block)["observed"]
    assert parsed["redirect_chain"] == ["https://agency.gov/a", "https://agency.gov/final"]
    assert parsed["http_status"] == 200


def test_replace_observed_block_leaves_the_rest_byte_identical():
    mod = _load_checker()
    block = mod.render_observed({"checked": "2026-08-04", "reachable": True, "http_status": 200,
                                 "final_url": "https://agency.gov/final", "redirect_chain": [],
                                 "fingerprint_result": "no-baseline"})
    out = mod.replace_observed_block(SAMPLE_ENTRY, block)
    before = [ln for ln in SAMPLE_ENTRY.splitlines() if not ln.startswith(("observed:", "  "))]
    after = [ln for ln in out.splitlines() if not ln.startswith(("observed:", "  "))]
    assert before == after, "only the observed block may change"
    assert "A multi-line block scalar that must survive untouched." in out
    assert out.endswith("\n")


def test_write_observed_never_alters_status_fields():
    mod = _load_checker()
    import yaml as _y
    block = mod.render_observed({"checked": "2026-08-04", "reachable": False, "http_status": 404,
                                 "final_url": "https://agency.gov/gone", "redirect_chain": [],
                                 "fingerprint_result": "no-baseline"})
    entry = _y.safe_load(mod.replace_observed_block(SAMPLE_ENTRY, block))
    # A dead probe records facts; the lifecycle label stays a human's to change.
    assert entry["observed"]["reachable"] is False and entry["observed"]["http_status"] == 404
    assert entry["status"] == "live" and entry["status_source"] == "curator"
    assert entry["status_since"] == "2026-01-01"


def test_replace_observed_block_reports_a_missing_block_rather_than_guessing():
    mod = _load_checker()
    assert mod.replace_observed_block("id: x\nstatus: live\n", "observed:\n  checked: '2026-08-04'") is None


def test_fingerprint_result_is_no_baseline_without_a_stored_hash():
    mod = _load_checker()
    entry = {"source": {"canonical_url": "https://agency.gov"}}
    assert mod._fingerprint_result(entry, mod.Probe(200, ""), 5) == "no-baseline"


def test_fingerprint_result_declines_to_answer_when_the_body_is_unavailable(monkeypatch):
    mod = _load_checker()
    monkeypatch.setattr(mod, "_body_sha256", lambda *a, **k: None)
    entry = {"source": {"canonical_url": "https://agency.gov"}, "fingerprint": {"sha256": "abc"}}
    # None means "not observed" — the caller must leave the existing value alone
    # rather than manufacture a drift from a download that never completed.
    assert mod._fingerprint_result(entry, mod.Probe(200, ""), 5) is None


def test_fingerprint_result_detects_match_and_drift(monkeypatch):
    mod = _load_checker()
    entry = {"source": {"canonical_url": "https://agency.gov"}, "fingerprint": {"sha256": "abc"}}
    monkeypatch.setattr(mod, "_body_sha256", lambda *a, **k: "abc")
    assert mod._fingerprint_result(entry, mod.Probe(200, ""), 5) == "match"
    monkeypatch.setattr(mod, "_body_sha256", lambda *a, **k: "def")
    assert mod._fingerprint_result(entry, mod.Probe(200, ""), 5) == "drift"


def test_fingerprint_result_skips_comparison_on_an_unreachable_probe():
    mod = _load_checker()
    entry = {"source": {"canonical_url": "https://agency.gov"}, "fingerprint": {"sha256": "abc"}}
    assert mod._fingerprint_result(entry, mod.Probe(404, ""), 5) is None


def test_observed_reachable_follows_the_schema_not_the_flagging_rule():
    """observed.reachable is "did the probe get any response?", not "did it succeed".

    A bot-blocked 403 must record reachable: true with http_status: 403. Writing false
    there would relabel `blocked` as `dead` inside the entry itself — the exact
    conflation the checker's third rung exists to prevent.
    """
    mod = _load_checker()
    import yaml as _y
    for code, expected in ((200, True), (403, True), (404, True), (None, False)):
        block = mod.render_observed({"checked": "2026-08-04", "reachable": code is not None,
                                     "http_status": code, "final_url": None,
                                     "redirect_chain": [], "fingerprint_result": "no-baseline"})
        assert _y.safe_load(block)["observed"]["reachable"] is expected
