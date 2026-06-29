# Development

Climate Almanac is a **self-contained public repo** that is *developed* inside the
Willow fleet. This doc explains both layers so the project stays consistent with Willow's
tooling and conventions as they evolve — without leaking any fleet-specific config into the
public repository.

## Two layers

| Layer | Files | Committed? | Purpose |
|-------|-------|-----------|---------|
| **Public project** | `pyproject.toml`, `requirements.txt`, `scripts/`, `schema/`, CI | yes | Builds, validates, and lints standalone — no fleet required. External contributors and GitHub CI use only this. |
| **Fleet overlay** | `.mcp.json`, `.venv/`, `.willow/` | **no** (gitignored) | Wires the folder into the Willow fleet (MCP memory, Kart, Grove) on the maintainer's machine. Local only. |

The split is deliberate: anyone can clone and contribute with just Python, while fleet
agents working the folder get full memory/execution tooling.

## Public project setup (anyone)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"      # jsonschema, PyYAML, ruff, pytest
python scripts/validate.py
python scripts/build_index.py
ruff check .                 # lint before pushing — config in pyproject.toml
```

`pyproject.toml`'s `[tool.ruff]` mirrors the Willow fleet's lint settings (same
`target-version`, the same `scripts/** = E402` ignore), so code written here is consistent
with the rest of the stack and won't bounce when moved between repos.

## Fleet overlay (maintainer / Willow agents)

`.mcp.json` (gitignored) registers the Willow MCP server **by absolute path to the
willow-2.0 launcher** (`sap/unified_mcp.sh`). Because it references Willow live rather than
copying any config, the overlay automatically tracks changes to Willow's MCP server, tool
registry, and env — it never drifts. An agent (Claude Code, etc.) opening this folder gets:

- **Fleet memory** — `willow_remember`, `kb_search`, `soil_*`, `handoff_*`
- **Execution plane** — `agent_task_submit` + `kart_task_run` (shell work runs in Kart, not
  raw Bash — same rule as the rest of the fleet)
- **Grove** — fleet messaging

If you change agent identity or fleet paths in willow-2.0, mirror the same edit here (or
re-copy willow-2.0's `.mcp.json`); the env block is the only thing this file pins.

## Conventions inherited from Willow

These are not re-documented here — Willow is the source of truth:

- **Worktree + PR for every change.** No direct commits to `main`.
- **Run `ruff check .` before pushing.** Lint CI is enforced.
- **Shell work goes through Kart** (`agent_task_submit` / `kart_task_run`), not agent Bash.
- **Search memory before building**; record decisions in the fleet KB.

## Keeping in lockstep with Willow

- **MCP / tools:** automatic — `.mcp.json` points at willow-2.0's launcher, so server and
  tool changes flow through with no action.
- **Lint rules:** when Willow's `[tool.ruff]` changes materially, update this repo's
  `pyproject.toml` to match. (Kept as an independent file, not a symlink, so the public repo
  stays clonable without willow-2.0 present.)
- **Python runtime:** the MCP server runs on willow-2.0's own interpreter via the launcher;
  this repo's `.venv` only needs the two runtime deps (`jsonschema`, `PyYAML`) plus dev
  tools. They are intentionally decoupled.
