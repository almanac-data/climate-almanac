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
    monkeypatch.setattr(mod, "_curl", lambda url, t, ua: (403, ""))
    code, note = mod._probe("https://bls.gov", 5, headless=False)
    assert code == 403 and "cannot auto-verify" in note


def test_probe_headless_upgrades_block_to_ok(monkeypatch):
    mod = _load_checker()
    monkeypatch.setattr(mod, "_curl", lambda url, t, ua: (403, ""))
    monkeypatch.setattr(mod, "_probe_headless", lambda url, t: (200, ""))
    code, note = mod._probe("https://bls.gov", 5, headless=True)
    assert code == 200 and "headless" in note


def test_probe_headless_failure_never_flags_dead(monkeypatch):
    mod = _load_checker()
    # Headless rung can't run / can't reach -> stay blocked, never report dead.
    monkeypatch.setattr(mod, "_curl", lambda url, t, ua: (403, ""))
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
