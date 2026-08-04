# Catalog Entry Schema v2 — design rationale

**Status:** proposal · **Supersedes:** `schema/catalog-entry.schema.json` (v1) · **Date:** 2026-06-30

This document explains *why* v2 looks the way it does. The machine-readable contract is
`schema/catalog-entry.schema.json`; this file is the reasoning behind it, so contributors inherit
the decisions and not just the field list. Every new or changed field below traces back to one of
the five rules in [The Constitution](#the-constitution) or one of the [five findings](#what-broke-in-v1)
from pressure-testing v1 against a real dead link.

---

## Why v2 exists — the worked example

v1 was pressure-tested against a real, verifiable takedown: the **2017 removal of the EPA Climate
Change website**. Probing the canonical URL today:

```
GET https://www3.epa.gov/climatechange/
→ 200 OK
→ final_url: https://www.epa.gov/climate-change   (a different, 2026-rebuilt page)
```

A v1 reachability checker scores this **`live`** — it returned `200`. But the resource a catalog
entry pointed at is **gone**: the URL silently redirects to a replacement page with different
content. v1 had:

- no way to record that the probe **redirected** (`final_url` had nowhere to live),
- no status value for **"alive but serving something else"**,
- no way to rank recovery sources when the **publisher itself removed the data** (its `legitimacy`
  ranking put the publisher on top — exactly backwards for a takedown),
- no honest account of authenticity for a resource we **never captured while it was live**.

The archived original *does* survive and *is* machine-discoverable:

```
GET https://archive.org/wayback/available?url=www3.epa.gov/climatechange
→ {"closest": {"available": true, "timestamp": "20170117012538", ...}}
```

v2 is the schema that can tell this whole story truthfully.

---

## The Constitution

The Almanac is **neutral availability infrastructure — a generator, not a watchdog.** Neutral about
content, partisan only about availability. Five rules; every field obeys one.

1. **Uniform disappearance.** No "censored" category. A politically-pulled dataset and a broken
   server migration are the same event: `gone`. Neutrality is structural — the schema has nowhere
   to put a side.
2. **Recovery ranks by authenticity, never authority.** Trust the math
   (`hash-verified` → `cross-archive` → `timestamped` → `asserted`). Who runs a mirror is irrelevant
   if the bytes verify.
3. **Authority lives only in the reference piece.** "Who is the official publisher" describes the
   canonical source and has **zero weight** in recovery ranking. This wall stops the v1 inversion.
4. **Permission is a gate, not a rank.** Impermissible copies are filtered out before ranking,
   never ranked low.
5. **Log facts, not motive.** Date went dark, redirect target, current domain controller — all
   observable. *Why* — never. Facts imply the story; the catalog does not narrate it.

---

## What broke in v1

| # | Finding | v2 fix |
|---|---------|--------|
| 1 | `legitimacy` ranked by authority → inverts for takedowns | `recovery[].authenticity` tiers (rule 2/3) |
| 2 | status enum can't express "alive but different content" | new states `superseded`, `redirected`, `revised` |
| 3 | `hash_match: bool` is a fantasy for entries cataloged after death | `recovery[].authenticity` honest tiers (no fiat) |
| 4 | one row = one artifact, but takedowns are collections | optional `collection` as a *derived view* |
| 5 | the probe's `final_url` had nowhere to be recorded | new `observed` block |

---

## The shape

One entry = **one curated resource** — "one thing a person would name when they say *we lost X*."
Not a file, not a whole site. Granularity is a curation decision, not a schema rule.

```yaml
# ── IDENTITY ───────────────────────────────────────────────
id: epa-climate-change-site            # stable kebab slug, matches filename, never reused
type: document                         # dataset | paper | textbook | document   (NEW, required)
title: EPA Climate Change Website
description: EPA's public climate science, impacts, and state/local resources hub as published through Jan 2017.
publisher: U.S. Environmental Protection Agency
topics: [climate, policy, public-health]
collection: epa-2017-takedown          # OPTIONAL — a derived view, not a monitored entity (finding #4)

# ── REFERENCE (authority lives here, and ONLY here — rule 3) ─
source:
  canonical_url: https://www3.epa.gov/climatechange/
  identifiers:                         # was v1 `source.doi`; now type-agnostic map
    doi: null                          #   dataset → DOI
    # arxiv / pmid / isbn / handle as applicable

# ── ACCESS (unchanged from v1) ─────────────────────────────
access:
  method: [web]
  auth_required: false

# ── MONITOR ────────────────────────────────────────────────
# fingerprint = baseline captured WHILE LIVE. Null/absent for retroactive entries — that's honest, not broken.
fingerprint:
  sha256: null                         # we never met this resource alive → no baseline
  etag: null
  content_length: null
  captured: null
  algo: sha256

# observed = pure machine facts from the last probe. No interpretation. (finding #5, rule 5)
observed:
  checked: 2026-06-30                  # was v1 `last_checked`
  reachable: true
  http_status: 200
  final_url: https://www.epa.gov/climate-change    # ← the redirect v1 couldn't record
  redirect_chain: [https://www.epa.gov/climate-change]
  fingerprint_result: no-baseline      # match | drift | no-baseline

# status = derived lifecycle label; auditable against `observed`; human-overridable.
status: superseded                     # live|revised|moved|redirected|superseded|dark|frozen
status_since: 2017-04-28               # when the CURRENT status was first observed — the catalog's invalid_at
status_source: curator                 # auto | curator  (who assigned it)

# ── RECOVER (ranked by authenticity, gated by permission — rules 2/3/4) ─
recovery:
  - via: wayback
    url: http://web.archive.org/web/20170117012538/https://www.epa.gov/climatechange
    authenticity: timestamped          # hash-verified | cross-archive | timestamped | asserted
    permission: ok                     # ok | review | excluded   (excluded = retained for audit, never surfaced)
    captured: 2017-01-17
    notes: Archive dated before the takedown; no live baseline to hash against.
  - via: community
    url: https://envirodatagov.org/...
    authenticity: asserted
    permission: review
    captured: null

# ── TYPE-SPECIFIC (only the block matching `type` is expected; soft-warn if absent) ─
coverage:                              # dataset / document
  spatial: national
  temporal: 1997-2017
  cadence: irregular
# bibliographic:                       # paper / textbook
#   authors: [...]
#   published: 2015-03-09
#   venue: ...
#   version: v1

# ── PROVENANCE / LEGAL (unchanged) ─────────────────────────
license: public-domain (US Gov work)
attribution: U.S. Environmental Protection Agency
notes: null
```

---

## Field-by-field: what changed and why

### New: `type` *(required)* — findings, generalization
`dataset | paper | textbook | document`. The discriminator that lets one row hold a NOAA dataset and
an arXiv paper identically. Verticals become **tags**, not separate machines: one validator, one
checker, one recovery layer across all of them.

### Changed: `source.doi` → `source.identifiers` *(map)*
A paper has an arXiv id *and* a DOI; a textbook has an ISBN. A single field can't hold that. The map
costs nothing and enables recovery-by-identifier ("find any copy with DOI X"). v1's
`source.predecessor_url` is **removed** — it's subsumed by a `recovery[]` candidate with provenance,
which is strictly richer.

### New: `fingerprint` *(monitor baseline)* — finding #3, rule 2
Hash + cheap pre-check fields captured **while the resource is live**. This is what makes monitoring
*honest*: a pure 200-checker is blind to silent revision (the EPA case). **It is null/absent for any
entry cataloged after the resource died** — and that is correct, not a defect (honest tiers, no fiat).

### New: `observed` *(machine facts)* — finding #5, rule 5
The raw, uninterpreted result of the last probe: `reachable`, `http_status`, `final_url`,
`redirect_chain`, `fingerprint_result`, `checked`. The machine records facts here and **never assigns
a lifecycle label**. Replaces v1 `last_checked` (→ `observed.checked`).

### Changed: `status` enum + new `status_source` — finding #2
The state model. Machine proposes, human disposes; every label is auditable against `observed`.

| status | the facts say | needs baseline? |
|---|---|---|
| `live` | reachable, 2xx, no material redirect, fingerprint match or no-baseline-but-present | no |
| `revised` | reachable, 2xx, **same URL**, fingerprint **drift** | yes |
| `moved` | redirect, content **verified equivalent** to baseline | **yes** |
| `redirected` | redirect, **can't verify** equivalence (honest default) | no |
| `superseded` | redirect, content **differs** from original (EPA case) | yes (or curator) |
| `dark` | unreachable, or persistent 4xx/5xx | no |
| `frozen` | reachable but publisher-declared static | no |

`moved` is a claim you've *earned* (baseline confirms equivalence); `redirected` is the honest
fallback when you haven't. `mirrored` (v1) is **removed** — holding a copy is now expressed
recovery-side, not as a lifecycle state. `status_source: auto | curator` records who assigned the
label, so curator overrides are themselves a visible fact.

**`status_since` — the bitemporal boundary (the Willow spine).** `status` records the lifecycle
*state*; `status_since` records *when that state began* (date the current status was first observed).
Together they are the catalog's analog of Willow's KB-atom `valid_at` / `invalid_at` pair: a record
is never silently deleted, it is **time-bounded**. Without it, the EPA entry knows it is
`superseded` but not that it died in 2017 — the boundary lives only in prose. `status_since` makes
"when did this stop being true?" a queryable field, not a `notes` archaeology dig. (A full
`status_history[]` is the maximal version; deferred — `status` + `status_since` is the 80/20.)

### Changed: `archive` *(object)* → `recovery` *(ranked array)* — findings #1, #3; rules 2/3/4
The heart of v2. An ordered list of where the *real thing* can be retrieved, ranked by **verifiable
authenticity**, never by who runs the source:

- `authenticity`: `hash-verified` (matches our baseline) > `cross-archive` (≥2 independent archives
  agree) > `timestamped` (one archive dated before loss) > `asserted` (someone says so).
- `permission`: `ok` | `review` | `excluded`. The **gate** (rule 4): `excluded` candidates are
  retained for audit but **never surfaced or ranked**. We don't rank what we shouldn't point to.
- `via`, `url`, `captured`, `notes` describe the candidate.

Authority — "is this the official publisher" — appears **nowhere** in recovery. That is the wall
(rule 3) that keeps a censored replacement from outranking a faithful archive.

### New: `collection` *(optional)* — finding #4
A string id grouping entries that share a verifiable trait (a domain, a dark-date). A collection is a
**derived view, never a monitored entity**: its health is *computed* from member entries, never
stored; it carries no editorial label (rule 5 — "shared domain `epa.gov`, all dark since 2025-02" is
a fact; "the 2025 purge" is not). Recovery stays atom-level even when a candidate URL is
collection-scale (e.g. a Wayback subtree).

### New: `bibliographic` *(optional, type-specific)*
The paper/textbook counterpart to `coverage`: `authors`, `published`, `venue`, `version`. Only the
block matching `type` is expected; CI **soft-warns** (does not fail) if it's absent.

---

## Migration from v1

| v1 | v2 |
|----|----|
| *(no type field)* | `type` — set per entry (existing climate entries → `dataset`) |
| `source.doi` | `source.identifiers.doi` |
| `source.predecessor_url` | a `recovery[]` candidate (`via: predecessor`, `authenticity: timestamped`) |
| `last_checked` | `observed.checked` |
| `checksum` | `fingerprint.sha256` (baseline) or a `recovery[]` candidate's hash |
| `archive.{wayback_url, cloud_mirror, mirror}` | `recovery[]` entries (`via: wayback / cloud_mirror / self`) |
| `status: mirrored` | drop; express as a `recovery[]` candidate + appropriate lifecycle status |
| *(new)* | `fingerprint`, `observed`, `status_since`, `status_source`, `recovery[].authenticity/permission`, `collection`, `bibliographic` |

A migration script (`scripts/migrate_v1_v2.py`) can do the mechanical mappings; `type`,
`fingerprint` baselines, and `recovery.authenticity` tiers need human review per entry.

---

## Deliberately NOT in v2

The smallness discipline that kept v1 healthy:

- **No citation graph** (references-of / cited-by). That's a library; this is a catalog.
- **No content storage.** `recovery` *points*; it does not host. "Catalog, don't host" survives.
- **No motive / censorship fields** (rule 5). Structurally impossible to take a side.
- **No collection as a monitored object.** Collections are computed views, full stop.
- **No per-type required-field explosion.** Type-specific blocks are optional + soft-warned.

---

## Open items before code

*(Status check 2026-08-04: items 1–4 are shipped. **Item 2 was marked done on 2026-07-22 and
was not.** `check_links.py` reported status codes and never wrote `observed`, never captured
`final_url` or a redirect chain, and computed no `fingerprint_result` — so every entry's
`observed` block kept whatever a human first typed there, indefinitely, while the docs told
contributors a machine would fill it in. Now shipped for real via `--write-observed`. The
overstatement is recorded here rather than quietly overwritten, because a status line
claiming more than shipped is exactly how the gap survived unnoticed. Only item 5 remains
genuinely open.)*

1. ~~Generate `schema/catalog-entry.schema.json` v2 from this rationale.~~ **Done.**
2. ~~Update `scripts/check_links.py` to populate `observed` (capture `final_url`, redirect chain) and
   to compute `fingerprint_result` against any baseline.~~ **Done** (2026-08-04) — via
   `--write-observed`, opt-in so the default stays read-only. `fingerprint_result` is computed
   only where a `fingerprint.sha256` baseline exists, so the body is fetched and hashed only
   when there is something to compare it against; absent a baseline it records `no-baseline`,
   and where the artifact could not be fetched whole the existing value is left untouched
   rather than a `drift` manufactured from a partial read.
3. ~~Teach `scripts/validate.py` the type-conditional soft-warn for `coverage` vs `bibliographic`.~~ **Done.**
4. ~~Write `scripts/migrate_v1_v2.py`.~~ **Done.**
5. **Still open:** decide whether the daily job auto-promotes `live` → `revised`/`superseded`/`dark`, or only
   *proposes* a status change via issue for curator confirmation (leaning: propose, never auto-write
   a lifecycle label — `status_source` stays `curator` for anything but the cleanest cases).

   Half of this is now settled by construction. The daily job writes `observed` and opens a
   PR (`monitor/observed-refresh`) rather than pushing to the default branch, and it touches
   no lifecycle field: `status`, `status_source`, and `status_since` are never written by any
   automation. So the *facts* are captured automatically and the *label* still is not. What
   remains genuinely open is narrower than it was — whether a machine may ever propose a
   status change on its own (an issue, a PR body, a label), and if so on what evidence.
   `final_url` differing from `source.canonical_url` is the obvious first candidate, now that
   anything records it at all.
