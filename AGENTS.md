# Agent guide — Climate Almanac

Instructions for any AI coding agent (Claude Code, Codex, Cursor, compatible CLIs)
working in this repository. Read this before making changes.

## What this project is

Climate Almanac is an **open, versioned index of public climate data** — a catalog,
not a data warehouse. Each entry in `catalog/` is a human-reviewed, machine-validated
record pointing to an authoritative climate dataset (canonical source, how to access it,
where it's archived, and whether it's still reachable). It exists because climate.gov was
decommissioned and the curation/reachability layer it provided was lost.

## The one rule that defines the project

**Catalog, don't host.** This repo maps data; it does not store data bytes. Do not add
datasets, CSVs, NetCDF, GeoTIFFs, or any data payload to the repo. The *only* exception is
a deliberate, small, at-risk artifact mirrored under an entry's `archive.mirror` field —
and only after it's been discussed in an issue. If a task tempts you to commit data, stop:
the answer is almost always a catalog entry pointing to where the data lives.

## Repository map

```
schema/catalog-entry.schema.json   the contract every entry must satisfy (JSON Schema 2020-12)
catalog/<id>.yaml                  one curated dataset per file (source of truth)
catalog.json                       GENERATED build artifact — do not hand-edit
scripts/validate.py                schema + filename==id + uniqueness checks (CI gate)
scripts/build_index.py             catalog/*.yaml -> catalog.json
scripts/check_links.py             reachability checker (read-only; reports, never rewrites)
scripts/alert_on_dead_links.py     turns a check_links report into GitHub issues (idempotent; circuit-breaker)
.github/workflows/ci.yml           runs validate + a stale-index guard on every PR
.github/workflows/link-check.yml   daily reachability probe -> auto-opens/closes dead-link issues
```

## Working rules / invariants

1. **The schema is the contract.** Every `catalog/*.yaml` must validate against
   `schema/catalog-entry.schema.json`. Run `python scripts/validate.py` before committing.
2. **Filename equals id.** `catalog/foo-bar.yaml` must contain `id: foo-bar` (kebab-case).
3. **Rebuild the index after touching entries.** Run `python scripts/build_index.py` and
   commit the updated `catalog.json` in the same change. CI fails if it's stale.
4. **Never hand-edit `catalog.json`.** It is generated. Edit the YAML, regenerate.
5. **Verify before you assert.** Do not invent `last_checked` dates or URL reachability.
   If you can reach the network, confirm `source.canonical_url` and set `last_checked` to
   today (`YYYY-MM-DD`). If you cannot verify, say so in the PR — do not fabricate.
6. **Set `status` honestly:** `live` (reachable + maintained), `frozen` (reachable, no
   longer updated), `moved` (URL changed), `dark` (gone/404), `mirrored` (we hold a copy).
   If you mark something `dark`/`frozen`, add a `notes` line and a `archive.wayback_url`.
7. **Authoritative sources only.** Point to the publisher's canonical home, not a reposting.
8. **One dataset = one file = one PR.** Keep changes small and reviewable.

## Common tasks

```bash
pip install -r requirements.txt
python scripts/validate.py       # before any commit that touches catalog/
python scripts/build_index.py    # regenerate catalog.json after entry changes
python scripts/check_links.py    # verify which sources are still reachable (requires curl)
```

To add a dataset: copy an existing `catalog/*.yaml`, fill every required field, validate,
rebuild the index, open a PR. See `CONTRIBUTING.md` for the full checklist.

## Licensing

Catalog data (`catalog/`, `catalog.json`) is **CC0**; tooling (`scripts/`, schema, CI) is
**MIT**. Keep new tooling MIT-compatible and keep entries attribution-accurate — every entry
must credit its publisher in the `attribution` field, even though the index itself is CC0.

## Fleet development

This repo is public and self-contained, but is *developed* inside the Willow fleet. If a
local (gitignored) `.mcp.json` is present, you have fleet tooling: memory (`willow_remember`,
`kb_search`), the Kart execution plane (`agent_task_submit` / `kart_task_run` — use it for
shell work instead of raw Bash), and Grove. Inherited conventions: worktree + PR for every
change (never commit to `main` directly), and `ruff check .` before pushing. Full detail and
the public-vs-overlay split is in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md). None of the
fleet overlay ships in the public repo.

## Tone

This is public-interest infrastructure. Accuracy beats coverage: a small, correct, current
catalog is worth more than a large stale one. When unsure whether something is verifiable,
under-claim rather than over-claim.
