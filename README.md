# Climate Almanac

[![CI](https://github.com/almanac-data/climate-almanac/actions/workflows/ci.yml/badge.svg)](https://github.com/almanac-data/climate-almanac/actions/workflows/ci.yml)
[![Good first issues](https://img.shields.io/github/issues/almanac-data/climate-almanac/good%20first%20issue?label=good%20first%20issues&color=7057ff)](https://github.com/almanac-data/climate-almanac/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)

**An open, versioned index of public climate data — so the record survives when the websites don't.**

When [climate.gov](https://www.climate.gov) was decommissioned, the United States lost its
curated public home for climate science. The underlying data — NOAA, NCEI, NSIDC and others —
mostly still exists, scattered across agency endpoints. What vanished was the **map**: the
catalog that told you what existed, where it lived, how to get it, and whether it was still there.

Climate Almanac rebuilds that map. It is **a catalog, not a data warehouse.** Each entry is a
small, human-reviewed, machine-validated record pointing to an authoritative climate dataset:
its canonical source, how to access it, where it's archived, and — critically — whether it is
still reachable today.

> An almanac has always been a curated reference of climate and weather. This is that, for the
> open-data era: kept in version control, built by many hands, and designed to outlive any single
> website.

## Project stage
Climate Almanac is a **seed catalog, seeking stewards, prioritizing accuracy-over-coverage**. For details on our overarching philosophy and management guidelines, see [WHY_ALMANAC.md](WHY_ALMANAC.md) and [GOVERNANCE.md](GOVERNANCE.md).

## Why catalog-first

Mirroring petabytes of federal climate data is an enormous task — most of it is still served by the agencies. The real, unfilled gap is the **curation and reachability layer**.
A catalog is:

- **Sustainable** — a single maintainer can keep it accurate; it doesn't need a data center.
- **Useful immediately** — it's the index every downstream tool, researcher, and teacher needs.
- **A targeting system** — it tells you *which* datasets are actually going dark, so real
  preservation effort (mirroring) can be spent where it matters, not everywhere at once.

The `noaa-billion-dollar-disasters` entry is the thesis in one file: a high-value dataset NOAA
stopped updating in 2025, flagged `frozen` and marked for priority mirroring.

## What's here

```text
schema/catalog-entry.schema.json   # the contract every entry must satisfy
catalog/*.yaml                     # one curated dataset per file
scripts/validate.py                # schema + integrity checks (CI gate)
scripts/build_index.py             # catalog/*.yaml -> catalog.json
scripts/check_links.py             # reachability checker (the path to automated monitoring)
catalog.json                       # generated, machine-readable full index
## Using the catalog

The build artifact `catalog.json` is the machine-readable index — point tools at it.
Browse `catalog/` directly for the human-readable source of truth.

```bash
pip install -r requirements.txt
python scripts/validate.py       # check every entry
python scripts/build_index.py    # regenerate catalog.json
python scripts/check_links.py    # report which sources are still reachable
```

## Contributing

Adding a dataset is one pull request that adds one file to `catalog/`.
See [CONTRIBUTING.md](CONTRIBUTING.md). CI validates every entry against the schema.

New here? Pick a [**good first issue**](https://github.com/almanac-data/climate-almanac/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22) — verify one canonical URL, add one YAML file, open a PR.

## License

- **Catalog data** (`catalog/`, `catalog.json`) — [CC0 1.0](LICENSE-DATA) (public domain dedication).
  The cataloged datasets are works of the U.S. Government; this index of them is freely reusable.
- **Tooling** (`scripts/`, schema, CI) — [MIT](LICENSE-CODE).

## Acknowledgements

Stands on the shoulders of the federal-data-rescue community — including
[EDGI](https://envirodatagov.org/), Data Refuge, and the original
[climate-mirror](https://github.com/climate-mirror) effort. Climate Almanac focuses on the
dataset-catalog niche those projects don't centrally maintain.

Climate data belongs to everyone. Keeping it findable is the least we can do.
