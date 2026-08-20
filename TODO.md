# TODO

## Phase 1: Extract monolith into clean submodules

Each task: extract from `__main__.py` → create submodule → add unit tests → commit.

- [ ] P1.1 **schema.py** — Extract `TestTask`, `TestResult` dataclasses. Test construction, defaults, field types.
- [ ] P1.2 **scorers.py** — Extract `mcq_scorer` + `SCORERS` registry. Test each extraction fallback path, correct/incorrect/edge cases.
- [ ] P1.3 **usage.py** — Extract `fetch_ollama_usage`. Test API response parsing with mocked httpx, missing config, error handling.
- [ ] P1.4 **runner.py** — Extract `StatsCollector` + `run_single_test`. Test stats collection from events, token normalization, latency fallback, error handling.
- [ ] P1.5 **report.py** — Extract `compute_composite` + report formatting. Test composite formula with various inputs (free, cheap, expensive, zero-quality), test report output.
- [ ] P1.6 **cli.py** — Extract `main`/`async_main` (argparse, orchestration, output). `__main__.py` becomes thin entry point. Test argument parsing, orchestration flow.

## Phase 2: Extend submodules to full envisaged form

- [ ] P2.1 **schema.py** — Add `Score`, `TestReport`, `SuiteConfig`, `CategorySummary`, `OverallSummary`, `ComparisonReport` dataclasses from the analysis.
- [ ] P2.2 **scorers.py** — Add `exact_match`, `numeric_match`, `regex_extract`, `contains`, `json_valid`, `code_execution` scorers. Add `normalize_response` utility.
- [ ] P2.3 **loader.py** — Suite YAML loader with `!function` resolution, static + dynamic task generation, suite validation.
- [ ] P2.4 **runner.py** — `EvalRunner` class: suite execution loop, repeats support, per-task error handling, multi-task aggregation.
- [ ] P2.5 **report.py** — Category aggregation (mean ± std), overall summary, baseline comparison, YAML/JSON serialization.
- [ ] P2.6 **pricing.py** — Pricing file loader, cost computation from tokens × pricing, cost-per-correct-answer.
- [ ] P2.7 **cli.py** — Full CLI: `eval`, `suites`, `show` subcommands. `--suite`, `--model`, `--compare`, `--output` flags.
- [ ] P2.8 **suites/yoker_basic/** — The 30-task suite YAML across 5 categories (knowledge, reasoning, instruction, code, tool_use).

## Phase 3: Yoker modifications for cleaner plugin integration

- [ ] P3.1 Add `CommandSpec` dataclass to `yoker.plugins.manifest`.
- [ ] P3.2 Add `commands` and `config_sections` fields to `PluginManifest`.
- [ ] P3.3 Modify `yoker.__main__` to discover `CommandSpec`s from installed packages and dispatch dynamically.
- [ ] P3.4 Wire `yoker test` subcommand via the new discovery mechanism.
- [ ] P3.5 Add `ConfigIsMissing` exception to yoker core (if needed).
- [ ] P3.6 Clevis extensions for dynamic command registration and config injection (discover and request as needed).