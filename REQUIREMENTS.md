# Requirements

## Functional Requirements

### Test Task Definition
- [x] R1: Define test tasks with unique ID, category, prompt, expected answer, scorer type, and optional scorer config

### Multi-Scorer Support
- [x] R2: Support MCQ scorer with 4-stage fallback extraction (exact letter, answer pattern, standalone letter, paren pattern)
- [ ] R3: Support exact_match scorer with case sensitivity config
- [ ] R4: Support numeric_match scorer with tolerance config
- [ ] R5: Support regex_extract scorer with pattern and group config
- [ ] R6: Support contains scorer with case sensitivity config
- [ ] R7: Support json_valid scorer with optional schema validation
- [ ] R8: Support code_execution scorer with language and timeout config
- [ ] R9: Provide normalize_response utility for pre-processing responses before scoring

### Suite Format and Loading
- [ ] R10: Load test suites from YAML files
- [ ] R11: Support suite-level metadata (name, description, model)
- [ ] R12: Support category definitions with weight and description
- [ ] R13: Support static task definitions in suite YAML
- [ ] R14: Support dynamic task generation via `!function` YAML tags
- [ ] R15: Validate suites (required fields, scorer existence, ID uniqueness, category references)
- [ ] R16: Provide a 30-task reference suite (yoker_basic) across 5 categories

### Suite Execution
- [ ] R17: Execute all tasks in a suite through Yoker's SDK
- [ ] R18: Support multiple repeats per task for statistical reliability
- [ ] R19: Handle per-task errors gracefully (record error, continue suite)
- [ ] R20: Aggregate results across tasks and categories

### Metric Collection
- [x] R21: Collect input/output token counts with backend fallback (OpenAI/Anthropic → Ollama)
- [x] R22: Collect latency with backend-reported duration and wall-clock fallback
- [x] R23: Collect thinking/content character split from event stream
- [x] R24: Fetch Ollama API usage deltas (session/weekly) when available

### Scoring and Composite
- [x] R25: Compute per-task score (0.0–1.0) via configured scorer
- [ ] R26: Compute category-level aggregation (mean ± standard deviation)
- [ ] R27: Compute overall quality score (weighted by category)
- [x] R28: Compute composite score: quality × cost_score where cost_score = 1 / (1 + cost_per_correct × scale)

### Report Generation
- [x] R29: Print per-task detail (score, response, extracted, expected, tokens, latency, thinking %)
- [ ] R30: Print category summaries (mean, std, task count, correct count)
- [ ] R31: Print overall summary (quality, composite, total tokens, total latency)
- [ ] R32: Support baseline comparison output (deltas with regression flags)
- [ ] R33: Serialize reports to YAML format
- [ ] R34: Serialize reports to JSON format

### Regression Detection
- [ ] R35: Store baseline results from a reference run
- [ ] R36: Compare new runs against stored baseline
- [ ] R37: Report per-category and overall deltas
- [ ] R38: Flag significant regressions (configurable threshold)

### CLI Interface
- [x] R39: Provide CLI with `--model` flag (Phase 1: single hardcoded task)
- [ ] R40: Provide `eval` subcommand with `--suite`, `--model`, `--compare`, `--output`, `--repeats` flags
- [ ] R41: Provide `suites` subcommand to list available suites
- [ ] R42: Provide `show` subcommand to display suite contents without running
- [ ] R43: Maintain backward compatibility with `yoker-test --model X` syntax

### Pricing and Cost (DEFERRED per owner decision)
- [ ] ~~R44: Load pricing data from YAML file (per-model input/output token rates)~~ (deferred)
- [ ] ~~R45: Compute cost from token counts and pricing data~~ (deferred)
- [ ] ~~R46: Compute cost-per-correct-answer from token-based pricing~~ (deferred)
- [x] R44a: Use Ollama session/weekly usage % delta as cost factor (already implemented in usage.py + report.py)

### Multi-Turn Conversation Support
- [ ] R81: Support multi-turn tasks with `turns` field (list of role/content messages sent sequentially)
- [ ] R82: Capture full message exchange in `TestResult.messages` for multi-turn tasks
- [ ] R83: Extend scorer interface to access full conversation for multi-turn tasks
- [ ] R84: Support both `prompt` (single-turn) and `turns` (multi-turn) in suite YAML format
- [ ] R85: Maintain backward compatibility — single-turn tasks work unchanged

## Non-Functional Requirements

### Coding Standards
- [x] R47: 2-space indentation (matches yoker)
- [x] R48: Double quotes
- [x] R49: Line length: 100
- [x] R50: Ruff for formatting and linting
- [x] R51: Mypy for type checking (strict mode)
- [x] R52: Conventional commits with attribution

### Testing
- [x] R53: Unit tests for every module (pytest + pytest-asyncio)
- [x] R54: Mocked external dependencies (Yoker SDK, httpx)
- [ ] R55: Tests for all new Phase 2 modules (loader, pricing, extended runner/report)

### Compatibility
- [x] R56: Python >= 3.10
- [x] R57: Uses `str | None` union syntax
- [x] R58: `dataclasses` for all data structures

### Package Management
- [x] R59: uv as package manager
- [x] R60: Editable yoker dependency from `../yoker`
- [x] R61: Hatchling as build backend

### Error Handling
- [x] R62: Per-task errors don't abort the suite (Phase 1: single task, but pattern established)
- [x] R63: External API failures degrade gracefully (return None, continue)
- [x] R64: Missing config sections return None, not exceptions

### Configurability
- [ ] R65: Suite-driven task definitions (not hardcoded)
- [ ] R66: Scorer selection per-task via suite YAML
- [ ] R67: Category weights configurable
- [x] R68: Composite scale configurable

### Backend Integration
- [ ] R69: Support three execution paths through Yoker's SDK (`process()`, `agent()`, `backend.chat_stream()`)
- [ ] R70: Normalize UsageStats across providers (OpenAI/Anthropic → Ollama fallback)
- [ ] R71: Collect TTFT (time to first token) when streaming

### Baseline Registry
- [ ] R72: Store baseline results keyed by (Yoker version, model, suite version)
- [ ] R73: Load and match baselines by composite key
- [ ] R74: Support "latest" baseline reference for quick comparison

### Reference Model Set
- [ ] R75: Define fixed reference model set covering main backend paths (small Ollama, large Ollama, API model)

### Model Refusal Handling
- [ ] R76: Detect model refusals (empty response, safety filter triggers)
- [ ] R77: Record refusals as error with "refused" flag, score 0.0, continue suite

### Statistical Rigor
- [ ] R78: Support bootstrap confidence intervals for score reporting
- [ ] R79: Flag regressions using CI overlap (more rigorous than fixed threshold)
- [ ] R80: Support dual-filter numeric extraction (strict + flexible) with both scores visible

## Completed

- [x] R1 (Phase 1 — P1.1)
- [x] R2 (Phase 1 — P1.2)
- [x] R21 (Phase 1 — P1.4)
- [x] R22 (Phase 1 — P1.4)
- [x] R23 (Phase 1 — P1.4)
- [x] R24 (Phase 1 — P1.3)
- [x] R25 (Phase 1 — P1.2, P1.4)
- [x] R28 (Phase 1 — P1.5)
- [x] R29 (Phase 1 — P1.5)
- [x] R39 (Phase 1 — P1.6)
- [x] R44a (Phase 1 — P1.3, P1.5: Ollama usage % as cost factor, already implemented)
- [x] R47-R52 (Phase 1 — all tasks)
- [x] R53-R54 (Phase 1 — all tasks)
- [x] R56-R61 (Phase 1 — project setup)
- [x] R62-R64 (Phase 1 — P1.3, P1.4)
- [x] R68 (Phase 1 — P1.5)