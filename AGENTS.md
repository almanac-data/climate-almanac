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
a deliberate, small, at-risk artifact recorded as a `recovery[]` candidate — and only after
it's been discussed in an issue. `recovery[]` *points* to a copy held elsewhere; it never
holds one here. If a task tempts you to commit data, stop: the answer is almost always a
catalog entry pointing to where the data lives.

## Repository map

```
schema/catalog-entry.schema.json   the contract every entry must satisfy (JSON Schema 2020-12)
catalog/<id>.yaml                  one curated dataset per file (source of truth)
catalog.json                       GENERATED build artifact — do not hand-edit
scripts/validate.py                schema + filename==id + uniqueness checks (CI gate)
scripts/build_index.py             catalog/*.yaml -> catalog.json
scripts/check_links.py             reachability checker (reports; writes `observed` only with --write-observed)
scripts/alert_on_dead_links.py     turns a check_links report into GitHub issues (idempotent; circuit-breaker)
.github/workflows/ci.yml           runs validate + a stale-index guard on every PR
.github/workflows/link-check.yml   daily reachability probe -> auto-opens/closes dead-link
                                   issues, and opens an `observed`-refresh PR
```

## Working rules / invariants

1. **The schema is the contract.** Every `catalog/*.yaml` must validate against
   `schema/catalog-entry.schema.json`. Run `python scripts/validate.py` before committing.
2. **Filename equals id.** `catalog/foo-bar.yaml` must contain `id: foo-bar` (kebab-case).
3. **Rebuild the index after touching entries.** Run `python scripts/build_index.py` and
   commit the updated `catalog.json` in the same change. CI fails if it's stale.
4. **Never hand-edit `catalog.json`.** It is generated. Edit the YAML, regenerate.
5. **Verify before you assert.** Do not invent `observed.checked` dates or URL reachability.
   If you can reach the network, confirm `source.canonical_url` and set `observed.checked` to
   today (`YYYY-MM-DD`). If you cannot verify, say so in the PR — do not fabricate.
   **`observed` is machine-written.** Set `checked` and leave `reachable`, `http_status`, and
   `final_url` null — only `scripts/check_links.py --write-observed` fills those, from a real
   probe. Recording your own `curl` output there disguises a human check as a machine one.
   Report what you observed in the PR body; `status` + `status_source: curator` is where a
   human call belongs.
6. **Set `status` honestly:** `live`, `revised`, `moved`, `redirected`, `superseded`, `dark`,
   `frozen` — see `CONTRIBUTING.md` for the full table. If you mark something `dark`/
   `superseded`, add a `notes` line and, if you have one, a `recovery[]` candidate.
   Climate sources make the `redirected` / `moved` distinction load-bearing: agency
   reorganizations move pages constantly, and a redirect landing somewhere plausible is not
   evidence the data survived. `moved` only once equivalence is verified; `redirected`
   otherwise.
7. **Authoritative sources only.** Point to the publisher's canonical home, not a reposting.
8. **One dataset = one file = one PR.** Keep changes small and reviewable.

## Common tasks

```bash
pip install -r requirements.txt
python scripts/validate.py       # before any commit that touches catalog/
python scripts/build_index.py    # regenerate catalog.json after entry changes
python scripts/check_links.py    # verify which sources are still reachable (requires curl)
```

**Recording what the probe saw.** `check_links.py` reports and exits; it changes nothing
unless asked. `--write-observed` writes each probe's facts — including `final_url` and the
redirect chain, which matter more here than in most verticals — into the matching entry's
`observed` block, and nothing else. `status` is never touched: the machine records what it
saw, a curator decides what it means. Rebuild the index in the same change.

```bash
python scripts/check_links.py --write-observed && python scripts/build_index.py
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

---

*This guide is maintained locally rather than propagated from `almanac-template` — see
`LOCAL_OVERRIDES` in the org meta-repo's `scripts/propagate-engine.sh`, alongside this
vertical's `CONTRIBUTING.md`. Engine changes upstream will not reach this file automatically;
when the schema moves, it needs a hand edit.*
