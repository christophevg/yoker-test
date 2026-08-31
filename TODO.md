# TODO

> **Primary goal**: A report containing all Ollama cloud models ranked by
> "quality for usage" — quality scores with Ollama session/weekly usage as
> the cost factor. Token-based pricing computation is deferred (see Deferred
> section).

## Backlog

### Phase 2: Extend submodules to full envisaged form

#### P2.6: ~~Create pricing module~~ (DEFERRED — see Deferred section)

> **Owner decision**: Defer token-based pricing computation. For now, the
> cost factor is simply Ollama session/weekly usage % (already collected by
> `usage.py`). The main goal is a quality ranking report across all Ollama
> cloud models. Token-based pricing will be revisited when API models with
> real per-token costs need to be compared.

- [ ] ~~**P2.6: Implement pricing.py for cost computation**~~ (deferred)
  - Moved to Deferred section. Not needed for the current primary goal
    (quality ranking of Ollama cloud models using usage % as cost factor).


### Phase 2.5: Core Quality

> Intermediate quality phase requested by the owner, pulled forward from the
> remaining Phase 2 backlog. P2.5.1 and P2.5.2 are approved as specced
> (but NOT yet implemented — left unchecked).
>
> **Execution order**: P2.5.10 → P2.5.1 → P2.5.2 → P2.5.3 → P2.5.9 →
> P2.5.8 → P2.5.6 → P2.5.7. All quick wins and P2.5.9 have no
> dependencies; P2.5.7 is the capstone and uses everything before it.
>
> **Reorder reason**: P2.5.10 goes first (owner directive) — the owner
> wants the credit-usage + score-per-cost comparison of glm-5.2:cloud
> vs. newly released glm-5.3:cloud and glm-5.3-flash:cloud for a
> weekend blog post timed with today's model release, promoting Yoker
> and yoker-test.
> Research deliverables for P2.5.4 and P2.5.5 are complete — see
> `analysis/suite-research.md` and `analysis/sandbox-research.md`.


- [ ] **P2.5.2: Always-save results to `results/`** (Simple)
  - Always save to `results/{suite}_{model}_{timestamp}.yaml` (sortable ISO
    timestamp, colons replaced); `--output` overrides path; auto-create
    `results/`; print save path; full TestReport persisted
  - Future direction (explicitly NOT this phase): a "viewer"/replay tool
    reusing the verbose formatter for saved results
  - **Acceptance**: Every eval run leaves a
    `results/{suite}_{model}_{timestamp}.yaml` with the full TestReport; the
    save path is printed; `--output` overrides; `results/` auto-created

- [ ] **P2.5.3: Tighten scorers** (Simple-Moderate)
  - `count_bullet_lines`: add exact-count option (`exact: true` → 0.0 on
    wrong count); use on medium/hard instruction tasks
  - `tool_call_verify`: parse JSON and verify structure
    (`{"tool": ..., "args": ...}`) instead of substring matching
  - Update existing tests and the yoker_basic suite
  - **Acceptance**: `exact: true` scores 0.0 on wrong count.
    `tool_call_verify` scores 0.0 for malformed JSON or wrong structure.
    Suite and tests updated, all passing

- [ ] **P2.5.9: Harden `code_execution` sandbox** (Simple)
  - Per `analysis/sandbox-research.md`: HumanEval-style reliability_guard —
    nullify `os.system`, `os.remove`/`rmdir`/`removedirs`,
    `shutil.rmtree`/`move`, `subprocess.Popen`/`call`/`run`,
    `builtins.exit`/`quit`
  - Strip environment variables (minimal env: PATH, HOME, TMPDIR — prevents
    API-key leakage); run in a temp working directory as cwd
  - Keep existing timeout; skip RLIMIT_AS on macOS
  - Explicitly document "not a security sandbox"; stdlib only
  - **MUST land before P2.5.7** (the new suite leans on code tasks)
  - **Acceptance**: Code calling `os.system`/`shutil.rmtree`/`subprocess`
    scores 0.0 without side effects; child env is minimal; execution cwd is
    a temp dir; no external dependencies added; macOS supported (no RLIMIT_AS)

- [ ] **P2.5.8: Enrich post-run report** (Simple-Moderate)
  - Response preview, expected vs extracted column, error/refusal summary,
    per-category score distribution (e.g. "8/8 perfect, 2 partial, 1 fail")
  - Feeds the calibration loop's visibility (P2.5.7)
  - **Acceptance**: Report shows response preview, expected vs extracted,
    error/refusal summary, and per-category score distribution

- [ ] **P2.5.6: Multi-turn conversation support** (Moderate)
  - Pulled forward from P2.16. Optional `turns: list[{role, content}]` on
    TestTask; runner sends sequentially, captures full exchange in
    TestResult.messages; scorers receive full messages for multi-turn tasks
    (backward compatible: single-turn scorers get last response); loader
    parses `turns`; verbose + saved results show full exchange
  - Enables the genuinely challenging multi-step tasks
  - **Acceptance**: Multi-turn tasks execute correctly with the full
    exchange captured in `messages`; single-turn behavior unchanged; YAML
    `turns` parses and validates; verbose and saved results show full
    exchange

- [ ] **P2.5.7: Design and create the improved hard suite** (Moderate-Complex)
  - Informed by `analysis/suite-research.md`; design doc at
    `analysis/suite-design.md`
  - Elements: 10-choice expert-level MCQ (MMLU-Pro style, guessing floor
    10%); multi-step reasoning with exact-match final answers (MATH Level-5
    style); outcome-based code tasks with edge cases (strict
    code_execution); strict instruction compliance with 0.0 on violation
    (IFEval style); structured tool-call verification; multi-turn
    context-retention tasks (built on P2.5.6)
  - **Hard acceptance criteria — calibration loop**: refresh
    `docs/models.md` first; calibrate with reference models top=
    `glm-5.2:cloud`, mid=`qwen3.5:397b-cloud`, low=`gpt-oss:20b-cloud`
    (note: glm-5.3:cloud is newly available and may replace glm-5.2 as top
    reference); target 40–80% spread between strong and weak models,
    ≥15 points spread per category; any task where the top model scores
    ≥0.90 across repeats is deleted or tightened; strong model must NOT
    score 1.0 across all categories
  - **Acceptance**: Design doc at `analysis/suite-design.md`; suite
    validates; calibration runs show the target spread; no task scores the
    top model ≥0.90 across repeats; strong model not perfect across all
    categories

#### P2.10: Baseline registry

- [ ] **P2.10: Implement baseline registry for regression comparison**
  - Create `baselines/registry.yaml` with entries keyed by (yoker_version, suite_version, model)
  - Each entry: `yoker_version`, `suite_version`, `model`, `quality`, `efficiency`, `composite`, `timestamp`, optional `delta_from_previous`
  - Implement `load_baseline(yoker_version: str, suite_version: str, model: str) -> dict | None`: find matching baseline in registry
  - Implement `save_baseline(report: TestReport) -> None`: append result to registry, compute delta from previous entry for same (suite_version, model)
  - Implement `load_latest_baseline(suite_version: str, model: str) -> dict | None`: get most recent baseline for given suite + model
  - Support `--compare baselines/latest.yaml` as a convenience shortcut
  - **Satisfies**: FR8, FR14
  - **Acceptance**: `save_baseline` appends to registry with correct metadata. `load_baseline` finds matching entry by (yoker_version, suite_version, model). `load_latest_baseline` returns most recent. Delta from previous computed correctly. Missing registry file creates empty registry. Tests cover save/load/match/miss scenarios

#### P2.11: Landscape overview generation

- [ ] **P2.11: Implement landscape overview generation**
  - Implement `generate_landscape(reports: list[TestReport]) -> str`: aggregate multiple model reports into a Markdown compatibility table
  - Table columns: Model, Quality (stars), Efficiency (stars), Tool Use (✅/❌), Cost, Recommended For
  - Group by provider (Ollama vs API models)
  - Include "Known Issues" section for observed problems (e.g., `prompt_eval_count` returning None)
  - Output to `docs/model-compatibility.md` or stdout
  - CLI: `yoker-test landscape --reports results/*.yaml --output docs/model-compatibility.md`
  - **Satisfies**: FR12
  - **Acceptance**: `generate_landscape` produces valid Markdown with correct table structure. Multiple reports aggregate correctly. Star ratings computed from score thresholds. Known issues section populated from error patterns. CLI command works end-to-end. Tests cover aggregation, formatting, edge cases (single report, missing categories)

#### P2.12: Model refusal handling

- [ ] **P2.12: Implement model refusal detection and handling**
  - Detect model refusals: empty responses, safety filter triggers, nonsensical output patterns
  - Record as error with "refused" flag in `TestResult`
  - Score 0.0 for refused tasks
  - Continue suite execution (don't abort)
  - Include refusal count in report summary (per-category and overall)
  - **Satisfies**: FR16
  - **Acceptance**: Refusal detection correctly identifies empty/safety-filtered responses. Refused tasks have `error` set with "refused" indicator. Score is 0.0. Suite continues. Report includes refusal count. Tests cover detection patterns, edge cases (empty string, partial response, safety message)

#### P2.13: Bootstrap confidence intervals

- [ ] **P2.13: Implement bootstrap confidence intervals for statistical rigor**
  - Implement `bootstrap_ci(scores: list[float], n_bootstrap: int = 1000, confidence: float = 0.95) -> tuple[float, float]`: compute bootstrap confidence interval for a list of scores
  - Use in `aggregate_results`: report CI alongside mean ± std per category
  - Use in `compare_baseline`: flag regressions where CI bounds don't overlap (more rigorous than `|delta| > 2 × std`)
  - Add `--bootstrap` CLI flag to enable/disable (default: enabled)
  - **Satisfies**: FR17
  - **Acceptance**: `bootstrap_ci` returns correct CI bounds for known data. CIs reported in category summaries. Regression flagging uses CIs when available. CLI flag toggles behavior. Tests cover known distributions, edge cases (single score, all same scores)

#### P2.14: Dual-filter numeric extraction

- [ ] **P2.14: Implement dual-filter numeric extraction (strict + flexible)**
  - Extend `numeric_match` scorer to support dual-filter mode (config: `dual_filter: true`)
  - **Strict filter**: regex `"The answer is (\\-?[0-9\\.\\,]+)"` → take first match
  - **Flexible filter**: regex `"(-?[$0-9.,]{2,})|(-?[0-9]+)"` → take last match
  - When dual_filter enabled, report both strict and flexible scores in `Score.sub_scores`
  - Primary score uses flexible (more lenient), but strict score visible for debugging extraction gaps
  - **Satisfies**: FR2, FR17
  - **Acceptance**: Strict filter extracts "The answer is X" patterns. Flexible filter extracts last number. Dual mode reports both in sub_scores. Primary score uses flexible. Tests cover both filter patterns, no-match cases, multiple numbers in response

#### P2.15: Reference model set

- [ ] **P2.15: Define reference model set for regression baselines**
  - Create `docs/reference-models.md` documenting the fixed reference model set:
    - One small Ollama model (e.g., `llama3.2:3b`) — fast, cheap, local, deterministic
    - One larger Ollama model (e.g., `llama3.1:8b`) — more capable, still local
    - One API model (e.g., `gpt-4o-mini`) — different backend path (LiteLLM)
  - Document rationale: if all three show same delta, it's Yoker, not a model fluke
  - Document preference for Ollama models for baselines (deterministic)
  - Add `--reference-models` flag to `eval` for running against the reference set
  - **Satisfies**: FR15
  - **Acceptance**: Reference model set documented. `--reference-models` runs eval against all three models. Results comparable across models. Documentation explains rationale and deterministic preference

#### P2.16: Multi-turn conversation support (PULLED FORWARD — see Phase 2.5, P2.5.6)

> This task was pulled forward into Phase 2.5 as **P2.5.6**, which supersedes
> it. Kept here as a stub to avoid double implementation; the detailed spec
> below remains valid for P2.5.6. Remove this stub when P2.5.6 lands.

- [ ] **P2.16: Implement multi-turn conversation support in runner and suite format**
  - Extend `TestTask` to support multi-turn conversations: add optional `turns: list[dict]` field (list of `{"role": "user"/"assistant", "content": "..."}` messages). When `turns` is present, the runner sends them sequentially, collecting the full message exchange. When absent, falls back to single-turn `prompt` behavior.
  - Extend `TestResult` to capture full multi-turn exchange: the `messages: list[dict]` field (already in target schema) stores the complete conversation including model responses at each turn.
  - Extend `EvalRunner` to handle multi-turn tasks: iterate over `turns`, send each through Yoker, collect responses, build the `messages` list. The scorer receives the full conversation (last response or full exchange, depending on scorer).
  - Extend suite YAML format: tasks can define `turns` instead of (or alongside) `prompt`. Example:
    ```yaml
    - id: MT1
      category: reasoning
      difficulty: hard
      turns:
        - role: user
          content: "I have 3 apples and give 1 away. How many do I have?"
        - role: assistant
          content: "You have 2 apples."
        - role: user
          content: "I buy 5 more. How many now? Answer with just the number."
      expected: 7
      scorer: numeric_match
    ```
  - Extend scorer interface: scorers receive the full `messages` list for multi-turn tasks (the scorer decides whether to score the last response or the full exchange). Backward compatible: single-turn scorers receive the last response string as before.
  - Update `loader.py` to parse `turns` field in YAML.
  - **Satisfies**: FR4, FR18
  - **Acceptance**: Multi-turn tasks execute correctly — all turns sent sequentially, model responses captured at each turn, full `messages` list in `TestResult`. Scorers can access full conversation. Single-turn tasks still work unchanged. Suite YAML with `turns` field loads and validates correctly. Tests cover 2-turn, 3-turn, multi-turn with tool-use, error at turn 2 (continue to next task), single-turn backward compatibility.

### Phase 3: Yoker modifications for cleaner plugin integration

#### P3.1: Add CommandSpec to yoker.plugins.manifest

- [ ] **P3.1: Add CommandSpec dataclass to yoker.plugins.manifest**
  - Add `CommandSpec` dataclass to `yoker.plugins.manifest`: `name: str`, `handler: Callable[..., Any]`, `config_class: type | None = None`, `help: str = ""`, `default: bool = False`
  - **Satisfies**: FR9 (indirectly — enables `yoker test` subcommand)
  - **Acceptance**: `CommandSpec` constructs with required fields (`name`, `handler`). Optional fields default correctly (`config_class=None`, `help=""`, `default=False`). Dataclass is importable from `yoker.plugins.manifest`. Unit tests in yoker cover construction and defaults

#### P3.2: Extend PluginManifest with commands and config_sections

- [ ] **P3.2: Add commands and config_sections fields to PluginManifest**
  - Add `commands: list[CommandSpec]` field to `PluginManifest` (default: empty list via `field(default_factory=list)`)
  - Add `config_sections: dict[str, type]` field to `PluginManifest` (default: empty dict via `field(default_factory=dict)`)
  - Update `PluginManifest` parsing to read `commands` and `config_sections` from plugin manifests
  - **Acceptance**: `PluginManifest` accepts `commands` and `config_sections`. Empty defaults work. Existing plugin manifests without these fields still parse correctly. `config_sections` maps config path names to config classes (e.g., `{"test": TestConfig}`). Unit tests in yoker cover new fields

#### P3.3: Dynamic command discovery in yoker.__main__

- [ ] **P3.3: Modify yoker.__main__ to discover CommandSpecs from installed packages**
  - Scan installed packages for `PluginManifest` entries with `commands`
  - Register discovered `CommandSpec`s as argparse subcommands
  - Dispatch to `handler` callable when subcommand is invoked
  - Inject config sections requested by the plugin via `config_sections`
  - When no subcommands installed, print available packages with install instructions
  - **Acceptance**: `yoker test --suite yoker_basic` dispatches to yoker-test's handler. Unknown commands produce helpful error. Existing yoker subcommands still work. When no subcommands installed, `yoker` prints available packages. Integration test verifies end-to-end dispatch

#### P3.4: Wire yoker test subcommand via discovery

- [ ] **P3.4: Wire yoker test subcommand via the new discovery mechanism**
  - Add `__YOKER_MANIFEST__` to yoker-test's `__init__.py` with `CommandSpec(name="test", handler=..., config_class=TestConfig)`
  - Add `config_sections={"test": TestConfig}` to manifest
  - Ensure config injection works (yoker config passed to yoker-test via `config.test`)
  - Subcommand name is `test` — `yoker test`, not `yoker eval`
  - **Acceptance**: `yoker test eval --suite yoker_basic` works end-to-end. `yoker test suites` lists suites. Config is properly injected from yoker's config system at `config.test`

#### P3.5: Add ConfigIsMissing exception to yoker core

- [ ] **P3.5: Add ConfigIsMissing exception to yoker core**
  - Add `ConfigIsMissing(YokerError)` to `yoker.exceptions`: raised when no config file is found
  - Error message: "No yoker configuration found. Run `yoker init` to create one, or see https://yoker.dev for documentation."
  - If yoker-config is installed, it catches this exception and runs the bootstrap wizard
  - If yoker-config is not installed, the error surfaces with guidance
  - **Acceptance**: `ConfigIsMissing` is importable from `yoker.exceptions`. Raised by config loader when no config file found. Error message is clear and actionable. Unit tests in yoker cover the exception

#### P3.6: Clevis extensions for dynamic command registration

- [ ] **P3.6: Discover and request Clevis extensions for dynamic command registration and config injection**
  - Discover through yoker-test implementation what Clevis extensions are needed:
    - Dynamic command registration at runtime (not just `@configclass` at import time)
    - Build CLI from a list of `CommandSpec`s
    - `get_cmd()` with dynamic subcommands
    - Subcommands without a base Config class
    - Default subcommand designation
    - Dynamic config section injection (attaching plugin config classes at specified paths)
  - Create specific feature requests to Clevis project with concrete use cases from yoker
  - Start with a simple router (may not need Clevis for top-level dispatch), discover if Clevis is needed
  - **Acceptance**: Clevis extension needs documented with specific feature requests. If Clevis changes are needed and implemented: extensions work with yoker's plugin system. If gaps found: documented with specific requirements for follow-up. Router may work without Clevis for dispatch (only needed for config injection)

## Deferred

> Items deferred per owner decision. Kept in the docs for future reference
> but not part of the current active backlog.

### P2.6 (deferred): Token-based pricing module

- [ ] **P2.6 (deferred): Implement pricing.py for cost computation**
  - **Reason deferred**: Owner decision — the current primary goal is a
    quality ranking report across Ollama cloud models. The cost factor for
    now is Ollama session/weekly usage % (already collected by `usage.py`),
    not token-based pricing. Token-based pricing will be revisited when API
    models with real per-token costs need to be compared.
  - Original spec: `load_pricing(path)`, `compute_cost(tokens_in, tokens_out, pricing, model)`,
    `compute_cost_per_correct(total_cost, overall_score, n_tasks)`
  - Pricing format: `input_per_million`, `output_per_million` per model
  - Formula: `cost = (tokens_in × input_price + tokens_out × output_price) / 1_000_000`
  - Ollama (local) models → cost = 0.0
  - **Satisfies**: FR10 (deferred)
  - **Acceptance** (when un-deferred): `load_pricing` returns dict with model entries. `compute_cost` returns correct cost for known model, 0.0 for local/unknown. `compute_cost_per_correct` handles zero score. Tests cover known/unknown/local models, zero tokens, zero correct

## Done

### Phase 2.5: Core Quality

- [x] **P2.5.1: `--verbose` flag for full per-test detail** (2026-08-31)
  - `TestResult.expected` added (audit-copy) and populated at all four runner
    construction sites; `format_test_detail` pure helper + keyword-only
    `per_test_detail` on `format_console_report` (library API); `--verbose` on
    eval + top-level parsers (distinct `legacy_verbose` dest, collision
    regression-tested). **Owner feedback round**: verbose detail now STREAMS
    to stderr per test during the run (was final-report-only) — owner
    re-tested and approved. Final report stays compact; `--output` files
    unchanged. Scoped review cycles (round 0 + round 1) all PASS; 442 tests,
    make check green. **Merged via PR #11** (squash 2f1d89e)

### Phase 2.5: Core Quality (research deliverables)

- [x] **P2.5.10: Ollama credit usage statistics + score-per-cost ranking** (2026-08-29)
  - Implemented with the owner-approved backend-injection revision: no duplicated
    HTTP transport — `create_backend(config)` once per run, injected into all
    `yoker.agent()` calls, usage snapshots via `backend.fetch_usage()` (shared
    edges, 3-None circuit breaker); `extract_usage_metrics` pure normalization;
    per-test `usage_delta`/`requests_delta` + 6 optional `OverallSummary` fields;
    `rank_composite` (quality × 1/(1 + sessionΔ/max(n_correct,1) × 1000)) with
    composite-proximity ≈ tie flags, quality-only tie reorder, and Composite
    column in the quality ranking. 415 tests, make check green. **Merged via PR #10** (squash a252a80)
  - Note: `research/session-backend-usage.md` remains intentionally untracked
    (workflow-local, like reporting/ artifacts)
- [x] **P2.5.4: Research LLM evaluation frameworks** (2026-08-27)
  - Research for the improved hard suite completed. Full sourced report
    recovered from a lost session and archived at
    `analysis/suite-research.md` (informs P2.5.7)
- [x] **P2.5.5: Research Python code execution sandboxing** (2026-08-27)
  - Sandbox hardening research completed. Full sourced report recovered from
    a lost session and archived at `analysis/sandbox-research.md` (informs
    P2.5.9)

### Phase 1: Extract monolith into clean submodules

- [x] **P1.1: schema.py** — Extract `TestTask`, `TestResult` dataclasses. Test construction, defaults, field types.
- [x] **P1.2: scorers.py** — Extract `mcq_scorer` + `SCORERS` registry. Test each extraction fallback path, correct/incorrect/edge cases.
- [x] **P1.3: usage.py** — Extract `fetch_ollama_usage`. Test API response parsing with mocked httpx, missing config, error handling.
- [x] **P1.4: runner.py** — Extract `StatsCollector` + `run_single_test`. Test stats collection from events, token normalization, latency fallback, error handling.
- [x] **P1.5: report.py** — Extract `compute_composite` + report formatting. Test composite formula with various inputs (free, cheap, expensive, zero-quality), test report output.
- [x] **P1.6: cli.py** — Extract `main`/`async_main` (argparse, orchestration, output). `__main__.py` becomes thin entry point. Test argument parsing, orchestration flow.

### Phase 2: Extend submodules to full envisaged form

- [x] **P2.1: Add extended dataclasses to schema.py** (2025-07-22)
  - Extend `TestTask`: add `difficulty: str`, `system_prompt: str | None = None`; change `expected` to `Any`, `scorer` to `str | Callable`
  - Add `Score` dataclass: `value: float`, `extracted: str | None = None`, `sub_scores: dict[str, float] | None = None`, `explanation: str | None = None`
  - Extend `TestResult`: add `difficulty: str`, `repeat: int`, `prompt: str`, `messages: list[dict]`, `ttft_ms: float | None`, `scorer_name: str`, `sub_scores: dict[str, float] | None`; make `tokens_in`/`tokens_out` nullable (`int | None`)
  - Add `RunMetadata` dataclass: `suite: str`, `suite_version: str`, `model: str`, `provider: str`, `yoker_version: str`, `temperature: float`, `seed: int`, `repeats: int`, `timestamp: str`
  - Add `SuiteConfig` dataclass: `suite: str`, `version: str`, `description: str`, `repeats: int = 3`, `temperature: float = 0.0`, `seed: int = 42`, `max_tokens: int | None = None`, `tasks: list[TestTask]`, `task_generator: Callable | None = None`, `generator_config: dict | None = None`, `aggregation_weights: dict[str, float] | None = None`
  - Add `CategorySummary` dataclass: `score: float`, `std: float`, `n_tasks: int`, `avg_tokens_in: float`, `avg_tokens_out: float`, `avg_latency_ms: float`, `total_tokens: int`, `total_latency_s: float`
  - Add `OverallSummary` dataclass: `score: float`, `std: float`, `total_tokens_in: int`, `total_tokens_out: int`, `total_tokens: int`, `total_latency_s: float`, `avg_tokens_per_second: float`, `usage_delta: dict[str, float] | None` (Ollama session/weekly % delta — NOT token-based cost, which is deferred)
  - Add `TestReport` dataclass: `run: RunMetadata`, `results: list[TestResult]`, `summary: dict[str, CategorySummary]`, `overall: OverallSummary`, `comparison: ComparisonReport | None = None`; with `to_yaml()`, `to_json()`, `to_dict()` methods
  - Add `ComparisonReport` dataclass: `baseline: RunMetadata`, `delta: dict[str, float]`, `flagged: list[str]`
  - **Satisfies**: FR1, FR3, FR6, FR7, FR8, FR11, FR13, FR14
  - **Acceptance**: All new dataclasses construct correctly with required fields. Default values work. `TestReport.to_yaml()` produces valid YAML. `TestReport.to_json()` produces valid JSON. Existing tests still pass (with updated TestTask/TestResult field additions). New tests cover construction and defaults for each new dataclass. `OverallSummary` uses `usage_delta` (Ollama % delta) not token-based cost (deferred)
- [x] **P2.2: Implement additional scorers in scorers.py** (2025-07-23)
  - Add `normalize_response(response: str) -> str` utility: strip markdown/LaTeX formatting per simple-evals implementation (remove `**`, `$\boxed{`, `}$`, `\$', `$\text{`, `$`, `\mathrm{`, `\{`, `\text`, `\(`, `\mathbf{`, `{`, `\boxed`)
  - Add `exact_match(task, response) -> float | Score`: normalize both strings, compare; config: `ignore_case` (default: false), `ignore_punctuation` (default: false)
  - Add `numeric_match(task, response) -> float | Score`: strip non-numeric except `.` and `-`, extract first number (`r'-?[\d.]+'`), compare with `tolerance` config (default: 0.0)
  - Add `regex_extract(task, response) -> float | Score`: apply `pattern` from scorer_config, extract `group` (default: 1), compare to expected
  - Add `contains(task, response) -> float | Score`: check if expected string appears in response; config: `ignore_case` (default: false)
  - Add `json_valid(task, response) -> float | Score`: strip code fences, `json.loads()`, optionally check `required_keys` config
  - Add `code_execution(task, response) -> float | Score`: extract code from fences (```python or ``` or raw), exec in sandbox with `timeout` config, run `test_cases` config, score = cases_passed / total
  - Update `mcq_scorer` to 6-stage fallback: (1) exact A-D, (2) `Answer: B` pattern, (3) `\b[ABCD]\b` on first line, (4) `^([ABCD])` paren pattern, (5) first standalone A-D in response, (6) no match → 0
  - Change scorer return type to `float | Score` (not `tuple[float, str | None]`)
  - Register all scorers in `SCORERS` dict
  - Consider dual-filter mode for `numeric_match` (strict + flexible extraction, see P2.14)
  - **Satisfies**: FR2, FR17
  - **Acceptance**: Each scorer returns `1.0` or `Score(value=1.0, ...)` for correct, `0.0` for incorrect, `0.0` for extraction failure. `code_execution` returns `Score` with `sub_scores` per test case. `normalize_response` tested with markdown/LaTeX patterns. All edge cases tested (empty response, missing config, malformed input). Existing MCQ tests updated for 6-stage fallback
- [x] **P2.4: Implement EvalRunner in runner.py** (2025-07-24)
  - Add `EvalRunner` class: `__init__(self, tasks: list[TestTask], repeats: int = 3, temperature: float = 0.0, seed: int = 42)`, `async run(self, model: str, config: Any) -> TestReport`
  - Execute all tasks × repeats through Yoker's SDK
  - Support three execution paths: `yoker.process()` for standard tasks, `yoker.agent()` for tool-use tasks, `backend.chat_stream()` for direct backend access
  - Collect per-repeat `TestResult` (with `repeat` index)
  - Collect TTFT (time to first token) when streaming via `backend.chat_stream()`
  - Aggregate per-repeat results: mean score, summed tokens, mean latency
  - Handle per-task errors gracefully: record error, score 0.0, continue suite
  - Detect model refusals (empty response, safety filter) — record as error with "refused" flag (see P2.12)
  - Collect `RunMetadata` (suite, version, model, provider, yoker version, temperature, seed, repeats, timestamp)
  - Assemble `TestReport` with all results, category summaries, overall summary
  - Keep existing `StatsCollector` and `run_single_test` for backward compatibility
  - **Satisfies**: FR4, FR5, FR13, FR16
  - **Acceptance**: `EvalRunner.run()` executes all tasks × repeats, returns `TestReport`. Repeats produce per-repeat `TestResult` entries. Task errors don't abort the suite. All existing `run_single_test` tests still pass. New tests mock Yoker SDK and verify aggregation, error handling, repeat logic, RunMetadata collection
- [x] **P2.3: Implement loader.py for suite YAML loading** (2026-08-22)
  - Add `pyyaml` dependency to pyproject.toml
  - Implement `load_suite(path: str | Path) -> SuiteConfig`: parse YAML, resolve `!function` tags to Python callables, generate dynamic tasks, return `SuiteConfig`
  - Implement custom YAML constructor for `!function` tag: resolve `module.path.function` notation by importing module and getting attribute, call at load time, inject result
  - Support `task_generator` field: if present, call with `generator_config` → get `list[TestTask]`
  - Support `scorers` section: per-suite scorer config overrides
  - Support `aggregation.weights`: category weighting
  - Implement `validate_suite(config: SuiteConfig) -> list[str]`: check required fields present, all scorer names exist in `SCORERS` (or are callables), task IDs unique
  - Return list of validation errors (empty = valid)
  - **Satisfies**: FR3
  - **Acceptance**: Loading a valid YAML suite returns `SuiteConfig` with all tasks expanded. `!function` tags resolve and call Python functions. `task_generator` produces tasks dynamically. Invalid suites produce specific validation error messages. Missing file raises `FileNotFoundError`. Malformed YAML raises parse error. Unresolvable `!function` fails with clear error at load time
- [x] **P2.5: Implement report aggregation and serialization in report.py** (2025-07-26)
  - Add `aggregate_results(results: list[TestResult], weights: dict[str, float] | None) -> dict[str, CategorySummary]`: compute per-category score (mean), std, n_tasks, avg_tokens_in, avg_tokens_out, avg_latency_ms, total_tokens, total_latency_s
  - Add `summarize_overall(results: list[TestResult], category_summaries: dict[str, CategorySummary], weights: dict[str, float] | None, usage_delta: dict[str, float] | None) -> OverallSummary`: compute weighted score, std, total_tokens_in/out, total_tokens, total_latency_s, avg_tokens_per_second; use Ollama usage delta (session/weekly %) as the cost factor — NOT token-based pricing (deferred)
  - Add `compare_baseline(current: TestReport, baseline: TestReport) -> ComparisonReport`: compute per-category and overall deltas, flag where `|delta| > 2 × std`
  - Add `format_console_report(report: TestReport) -> str`: format full multi-task report (per-task detail, category summaries, overall summary with quality ranking, optional comparison with regression flags)
  - Add `format_quality_ranking(reports: list[TestReport]) -> str`: format a ranking table of all models sorted by quality, with usage % as cost factor — this is the primary deliverable
  - Implement `TestReport.to_yaml()`, `TestReport.to_json()`, `TestReport.to_dict()` (can be in schema.py or report.py)
  - Keep existing `compute_composite` and `print_report` for backward compatibility
  - **Satisfies**: FR6, FR7, FR8, FR12, FR17
  - **Acceptance**: `aggregate_results` produces correct mean/std/efficiency metrics for sample data. `summarize_overall` computes weighted quality correctly, uses Ollama usage % as cost factor (not token-based pricing). `compare_baseline` produces correct deltas and flags regressions where `|delta| > 2 × std`. `format_console_report` outputs readable multi-task report. `format_quality_ranking` produces a model ranking table sorted by quality. `to_yaml()`/`to_json()` produce valid serialized output. Existing `compute_composite` and `print_report` tests still pass
- [x] **P2.7: Implement config.py and public API in __init__.py** (2025-07-26)
- [x] **P2.8: Implement full CLI with subcommands in cli.py** (2025-07-26)
  - Refactor `main()` to use `argparse` subparsers: `eval`, `suites`, `show`
  - `eval` subcommand: `--suite` (required), `--model` (default from suite), `--compare` (baseline path), `--output` (file path for YAML/JSON), `--repeats` (default: from suite config)
  - `suites` subcommand: list available suites from `suites/` directory
  - `show` subcommand: `--suite` (required), display suite contents (tasks, categories, baseline) without running
  - `eval` flow: load suite → validate → create `EvalRunner` → run → generate `TestReport` → format console output → optionally serialize to file
  - Keep backward compatibility: `yoker-test --model X` still works (redirects to `eval --suite yoker_basic`)
  - **Satisfies**: FR9
  - **Acceptance**: `yoker-test eval --suite yoker_basic --model glm-5.2:cloud` runs suite and prints report. `yoker-test suites` lists available suites. `yoker-test show --suite yoker_basic` displays suite contents. `--output results.yaml` writes serialized report. `--repeats 3` overrides suite default. Existing CLI tests updated for new interface
  - Create `config.py` with `TestConfig(yoker.Config)`: extends yoker Config for test-specific settings (suite, model, compare, output, repeats)
  - Update `__init__.py` to export public API: `evaluate`, `EvalRunner`, `TestTask`, `TestReport`, `Score`
  - Implement `async evaluate(suite: str, model: str, compare: str | None = None) -> TestReport`: load suite from YAML (by name or path), create `EvalRunner`, run, optionally compare baseline, return `TestReport`
  - **Satisfies**: FR11
  - **Acceptance**: `from yoker_test import evaluate, EvalRunner, TestTask, TestReport, Score` works. `await evaluate(suite="yoker_basic", model="glm-5.2:cloud")` returns `TestReport`. `TestConfig` extends `yoker.Config` and is importable. Tests mock the runner and verify `evaluate()` orchestration
- [x] **P2.9: Create suites/yoker_basic/ with 30-task suite YAML** (2026-08-27)
  - Created `suites/yoker_basic/suite.yaml` with 30 tasks across 5 categories:
    - **knowledge** (8 tasks): factual MCQ questions, scorer: mcq
    - **reasoning** (8 tasks): math and logic, scorer: numeric_match
    - **instruction** (6 tasks): format constraint compliance, scorer: custom (structural)
    - **code** (4 tasks): Python code generation, scorer: code_execution
    - **tool_use** (4 tasks): tool call scenarios, scorer: custom (tool_call_verify)
  - Each task has: id, category, difficulty (easy/medium/hard), prompt, expected, scorer, scorer_config
  - Suite metadata: `suite: yoker_basic`, `version: "1.0"`, `repeats: 3`, `temperature: 0.0`, `seed: 42`, `max_tokens: 4096`
  - Aggregation weights: knowledge 0.25, reasoning 0.25, instruction 0.20, code 0.15, tool_use 0.15
  - Included dynamic tasks using `!function` tags (random math problems)
  - Created `suites/yoker_basic/generators.py` with generator functions for dynamic tasks
  - Created `suites/yoker_basic/scorers.py` with custom scorers (count_bullet_lines, tool_call_verify)
  - **Satisfies**: FR3
  - **Acceptance**: Suite loads successfully via `loader.load_suite()`. All 30 tasks parse correctly. Dynamic tasks generate properly. `validate_suite()` returns no errors. `yoker-test show --suite yoker_basic` displays all 30 tasks. `yoker-test eval --suite yoker_basic` runs all 30 tasks end-to-end. Category distribution is 8/8/6/4/4
  - **Merged via PR #9**
