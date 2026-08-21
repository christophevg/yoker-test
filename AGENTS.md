# AGENTS.md

**IMPORTANT**
When you encounter issues with permissions, missing tools or tools failing to do what you want, DON'T try to work around this, notify and ask for directions how to proceed. Most of the time, the owner will make a configuration change to enable access, perform the one-off command for you or give instructions on how to proceed.

## Project

**yoker-test** is a model evaluation framework for
[Yoker](https://github.com/christophevg/yoker). It tests LLM models
through Yoker's actual backend pipeline, producing multi-dimensional
profiles: quality (correctness), efficiency (tokens, latency), and cost
(API usage). It doubles as a regression detector for Yoker itself — same
model + same suite + different Yoker version → score delta = Yoker's
change.

This project also serves as the **testbed for the Yoker package split**.
The patterns we establish here (CommandSpec, PluginManifest extension,
dynamic command discovery) will be the blueprint for extracting other
subcommands from the yoker monolith.

## Key Documents

| Document | Location | What it contains |
|---|---|---|
| Analysis & design | `../yoker/analysis/yoker-test-analysis.md` | Full architecture: framework vs config, data structures, scorers, regression testing, reliability, suite format, report format, module structure, phasing |
| Split analysis | `../yoker/analysis/yoker-split-analysis.md` | Yoker monolith split plan: package overview, config injection, Clevis extension needs, phasing strategy |
| Task backlog | `TODO.md` | Phase 1 (extract monolith), Phase 2 (extend to full form), Phase 3 (yoker modifications) |
| Target models | `docs/models.md` | All Ollama cloud-available model IDs to test against |
| Available models | `models.json` | Raw API response from Ollama model list endpoint |

## Repository Layout

```
yoker-test/
├── AGENTS.md              # this file
├── Makefile               # make run MODEL=<model>
├── README.md
├── TODO.md                # task backlog (phases 1-3)
├── pyproject.toml         # package config, yoker-test CLI entry point
├── uv.lock
├── yoker.toml             # local yoker config (enabled=true, C3 agents/skills)
├── src/yoker_test/
│   ├── __init__.py        # version, author
│   └── __main__.py        # monolith (to be refactored into submodules)
├── tests/                 # (to be created)
├── docs/
│   └── models.md          # target model IDs
└── models.json            # raw Ollama API model list
```

## Development Setup

- **Python**: >=3.10
- **Package manager**: uv
- **Yoker dependency**: editable from `../yoker` (see `[tool.uv.sources]` in pyproject.toml)
- **Virtual env**: `.venv/` (auto-created by uv)

## Running

```bash
make run                          # default model (glm-5.2:cloud)
make run MODEL=gpt-oss:20b-cloud  # specific model
uv run yoker-test --model <model> # direct
```

Requires a working yoker config (`~/.yoker.toml` or `./yoker.toml`)
with `enabled = true` and a configured backend (provider, model, API key).

## Coding Standards

- 2-space indentation (matches yoker)
- Double quotes
- Line length: 100
- Ruff for formatting and linting
- Mypy for type checking
- Conventional commits with attribution: `🤖 Implemented together with Yoker.`

## Workflow

1. **One component at a time**: extract from `__main__.py` → create
   submodule → add unit tests → commit. See TODO.md for the task list.
2. **Commit after each component** using the c3:commit skill.
3. **Phase 1** (extract) before **Phase 2** (extend) before **Phase 3**
   (yoker modifications).

## Important Rules

### Yoker modifications

Yoker is in a decent shape, but sometimes we may want to improve it to
make plugin development easier. **Do not work around yoker limitations
by guessing or trying hacks.** When you hit friction, ask the user which
direction to go. We can modify yoker and restart the session.

### C3 agents and skills

C3 is being migrated from its previous Claude Code focus to yoker. The
agents and skills are not fully migrated yet. **When you run into problems
with C3, ask the user.** We can fix C3, just like yoker, and restart the
session with C3 fixed and usable.

### Don't guess — ask

When in doubt about direction, preference, or approach: ask the user.
This is an important project setting the standard for many similar
projects to come. Clarity is more valuable than speed.

## Current State

The monolith `src/yoker_test/__main__.py` contains all code in one file:
schema (TestTask, TestResult), mcq_scorer, StatsCollector,
fetch_ollama_usage, run_single_test, compute_composite, and the CLI
entry point. It works end-to-end with a single hardcoded MCQ task.

Next step: Phase 1 — extract into submodules with unit tests, one
component at a time, starting with P1.1 (schema.py).
