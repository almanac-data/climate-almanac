# Contributing to Climate Almanac

Thank you for helping keep public climate data findable. Contributions are deliberately small and
reviewable: **one dataset = one file = one pull request.**

## Add a dataset

1. Copy an existing entry from `catalog/` as a starting point.
2. Create `catalog/<your-id>.yaml`. The filename (minus `.yaml`) **must** equal the entry's `id`,
   which is a kebab-case slug (e.g. `noaa-sea-level-rise`).
3. Fill in every required field (see `schema/catalog-entry.schema.json`). Required:
   `id, title, description, publisher, topics, source, access, license, attribution, status,
   last_checked`.
4. Verify the source URL yourself and set `last_checked` to today's date (`YYYY-MM-DD`).
5. Run the checks locally:
   ```bash
   pip install -r requirements.txt
   python scripts/validate.py
   ```
6. Open a PR. CI runs validation; a green check is required to merge.

## Status values

Set `status` honestly based on what you actually observe:

| status     | meaning                                                        |
|------------|----------------------------------------------------------------|
| `live`     | reachable and actively maintained                              |
| `frozen`   | reachable but no longer updated by the publisher               |
| `moved`    | the canonical URL has changed (update `source.canonical_url`)  |
| `dark`     | the source is gone / 404 — populate `archive` with a copy      |
| `mirrored` | this project (or a partner) hosts a copy in `archive.mirror`   |

If you mark something `dark` or `frozen`, add a note in `notes` explaining what you found, and if
possible a `archive.wayback_url`.

## Curation principles

- **Authoritative sources only.** Point to the publisher's canonical home, not a blog reposting it.
- **No data in this repo.** We catalog; we don't host bytes. The only exception is a deliberate,
  small, at-risk artifact mirrored under `archive.mirror` after discussion in an issue.
- **Provenance and attribution are mandatory.** Every entry must credit its publisher.
- **Accuracy over coverage.** A small, correct, current catalog beats a large stale one.

## Reporting a dead link

Open an issue (or a PR flipping the entry's `status`) if you find a source has gone dark or moved.
Reachability reports from `scripts/check_links.py` are welcome.
