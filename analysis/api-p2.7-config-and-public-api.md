# API Design: P2.7 — Config Module and Public API

**Date**: 2025-07-26
**Task**: P2.7 — Implement `config.py` and public API in `__init__.py`
**Context**: yoker-test Phase 2, extending the extracted monolith into full form

## Summary

This document designs two deliverables:

1. **`config.py`** — `TestConfig(yoker.Config)`: a config dataclass that
   extends yoker's base `Config` with test-specific fields (suite, model,
   compare, output, repeats).
2. **`__init__.py`** — public API exports including the `evaluate()`
   convenience function that orchestrates suite loading, evaluation, and
   optional baseline comparison.

The design follows the established yoker pattern of extending `Config` for
subcommand-specific settings (cf. `ChatConfig`, `ConfigCmdConfig` in
`yoker/cli/commands.py`).

---

## 1. TestConfig Design

### Owner's Proposal (from TODO.md)

> Create `config.py` with `TestConfig(yoker.Config)`: extends yoker Config
> for test-specific settings (suite, model, compare, output, repeats)

### Assessment: Works as specified

The owner's proposal is the correct approach. yoker has an established
pattern of subclassing `Config` to add domain-specific fields. Three
examples exist in the codebase:

| Class | Base | Added Fields |
|-------|------|-------------|
| `ChatConfig` | `Config` | `session_id`, `resume` |
| `RunConfig` | `Config` | `source`, `persist`, `session_id`, `dry_run` |
| `ConfigCmdConfig` | `Config` | `json`, `show_path`, `reveal` |

`TestConfig` follows the same pattern — it extends `Config` with
evaluation-specific fields. This is **not** a wrapper; it's configuration
inheritance for TOML/CLI integration.

### Wrapper Check

**Passes.** `TestConfig` is not a wrapper around a single yoker call. It
is a configuration dataclass that extends yoker's config hierarchy, exactly
as `ChatConfig` and `RunConfig` do. The Wrapper Check applies to classes
that add no behavior beyond delegating to an underlying SDK call —
`TestConfig` adds configuration fields, not delegation.

### TestConfig Fields

```python
from dataclasses import dataclass, field

from yoker.config import Config


@dataclass
class TestConfig(Config):
  """Configuration for yoker-test evaluation runs.

  Extends yoker's base :class:`Config` with test-specific fields.
  All base Config fields (backend, tools, permissions, etc.) are
  inherited and remain configurable via TOML or CLI.

  Fields:
    suite: Suite name or path to evaluate (e.g., "yoker_basic"
      or "suites/yoker_basic/suite.yaml").
    model: Model identifier to test (e.g., "glm-5.2:cloud").
      Overrides the model in the loaded yoker config's backend.
    compare: Optional path to a baseline report for regression
      comparison. When provided, the evaluate() function computes
      a ComparisonReport.
    output: Optional file path to write the serialized report
      (YAML or JSON, determined by file extension).
    repeats: Number of times to repeat each task. Defaults to 3.
      Overrides the suite's repeats setting when non-None.
  """

  suite: str = ""
  model: str = "glm-5.2:cloud"
  compare: str | None = None
  output: str | None = None
  repeats: int | None = None
```

### Design Decisions

1. **`suite: str`** — Accepts both suite names ("yoker_basic") and direct
   paths ("suites/yoker_basic/suite.yaml"). The resolution logic lives in
   the `evaluate()` function, not in the config.

2. **`model: str = "glm-5.2:cloud"`** — Default model matches the existing
   CLI default. The `evaluate()` function applies this to
   `config.backend.config.model` before running.

3. **`compare: str | None = None`** — Optional baseline path. When None,
   no comparison is performed. This keeps comparison opt-in.

4. **`output: str | None = None`** — Optional output file path. The CLI
   (P2.8) will use this to write reports. `evaluate()` does not write
   files — it returns the `TestReport` and the caller decides what to do
   with it. The `output` field is on the config for CLI integration.

5. **`repeats: int | None = None`** — `None` means "use the suite's
   repeats setting". A non-None value overrides the suite config. This
   is cleaner than a magic sentinel and aligns with the TODO spec: "--
   repeats (default: from suite config)".

6. **No `@configclass(cmd="...")` decorator** — `TestConfig` is not
   registered as a CLI subcommand in this task. P2.8 will add the CLI
   subcommand structure. For now, `TestConfig` is a plain dataclass
   usable programmatically. The `@configclass` decorator can be added
   later without breaking the API.

7. **Plain `@dataclass`, not Clevis `@configclass`** — yoker's `Config`
   uses `@dataclass` from the stdlib (via Clevis's re-export). Using
   `@dataclass` here is consistent with the base class. Clevis's
   `@configclass` decorator adds CLI subcommand registration, which is
   P2.8's concern.

### Import Strategy

```python
from yoker.config import Config
```

This is the same import used by `yoker/cli/commands.py`. The dependency
already exists in `pyproject.toml` (`yoker>=0.10.1`). No new dependencies.

---

## 2. `evaluate()` Function Design

### Owner's Proposal (from TODO.md)

> Implement `async evaluate(suite: str, model: str, compare: str | None
> = None) -> TestReport`: load suite from YAML (by name or path), create
> `EvalRunner`, run, optionally compare baseline, return `TestReport`

### Assessment: Works with minor refinement

The signature is correct. One refinement: the function needs access to
a yoker `Config` instance (for the runner). The question is how to
obtain it.

### Recommended Signature

```python
async def evaluate(
  suite: str,
  model: str,
  compare: str | None = None,
  *,
  config: Config | None = None,
  repeats: int | None = None,
) -> TestReport:
```

### Design Decisions

1. **`config: Config | None = None` (keyword-only)** — When None,
   `evaluate()` calls `get_yoker_config()` to load the default config.
   When provided, the caller's config is used directly. This enables:
   - Library usage: `await evaluate(suite="yoker_basic", model="x")`
     (auto-loads config)
   - Test usage: `await evaluate(suite="...", model="...", config=mock_config)`
     (inject for testing)
   - Advanced usage: caller pre-configures a `TestConfig` and passes it in

2. **`repeats: int | None = None` (keyword-only)** — Overrides the
   suite's repeats setting. `None` means use the suite default. Kept as
   a parameter (not just on config) because `evaluate()` is the public
   API — callers shouldn't need to construct a `TestConfig` just to set
   repeats.

3. **`compare` as positional** — Matches the owner's proposal. The
   baseline path is resolved by `load_suite()` (for suite-format
   baselines) or by a direct file path (for serialized reports).

4. **Keyword-only `config` and `repeats`** — The positional args
   (`suite`, `model`, `compare`) are the primary API. `config` and
   `repeats` are advanced overrides that callers pass by name.

### Suite Name Resolution

```
suite="yoker_basic"
  → suites/yoker_basic/suite.yaml (relative to cwd)

suite="suites/yoker_basic/suite.yaml"
  → direct path (if exists)

suite="/absolute/path/to/suite.yaml"
  → direct path
```

Resolution logic:

```python
def _resolve_suite_path(suite: str) -> Path:
  """Resolve a suite name or path to a suite.yaml file path."""
  # 1. If it's a direct path to an existing file, use it
  direct = Path(suite)
  if direct.exists():
    return direct.resolve()

  # 2. If it has a suffix (e.g., .yaml), treat as path (error if not found)
  if direct.suffix:
    raise FileNotFoundError(f"Suite file not found: {direct}")

  # 3. Otherwise, treat as a suite name: suites/{name}/suite.yaml
  named = Path("suites") / suite / "suite.yaml"
  if named.exists():
    return named.resolve()

  raise FileNotFoundError(
    f"Suite not found: {suite!r}. "
    f"Looked for: {direct} and {named}"
  )
```

This keeps resolution simple and predictable. The `suites/` directory
convention matches the TODO spec (P2.9: "Create `suites/yoker_basic/`").

### `evaluate()` Implementation Flow

```python
async def evaluate(
  suite: str,
  model: str,
  compare: str | None = None,
  *,
  config: Config | None = None,
  repeats: int | None = None,
) -> TestReport:
  # 1. Resolve suite path
  suite_path = _resolve_suite_path(suite)

  # 2. Load and validate suite
  suite_config = load_suite(suite_path)
  errors = validate_suite(suite_config)
  if errors:
    raise ValueError(f"Invalid suite: {', '.join(errors)}")

  # 3. Get or load yoker config
  if config is None:
    config = get_yoker_config()

  # 4. Determine effective repeats
  effective_repeats = repeats if repeats is not None else suite_config.repeats

  # 5. Create and run EvalRunner
  runner = EvalRunner(
    tasks=suite_config.tasks,
    repeats=effective_repeats,
    temperature=suite_config.temperature,
    seed=suite_config.seed,
    suite_name=suite_config.suite,
    suite_version=suite_config.version,
    aggregation_weights=suite_config.aggregation_weights,
  )
  report = await runner.run(model, config)

  # 6. Optional baseline comparison
  if compare is not None:
    baseline = _load_baseline(compare)
    report.comparison = compare_baseline(report, baseline)

  return report
```

### Baseline Loading

The `compare` parameter accepts a path to a serialized `TestReport`
(YAML or JSON). Loading logic:

```python
def _load_baseline(path: str) -> TestReport:
  """Load a baseline TestReport from a YAML or JSON file."""
  resolved = Path(path).resolve()
  if not resolved.exists():
    raise FileNotFoundError(f"Baseline file not found: {resolved}")

  with open(resolved, encoding="utf-8") as f:
    if resolved.suffix == ".json":
      data = json.load(f)
    else:
      data = yaml.safe_load(f)

  # Reconstruct TestReport from dict
  return TestReport.from_dict(data)
```

**Note**: `TestReport` currently has `to_dict()`, `to_json()`, `to_yaml()`
but no `from_dict()` / `from_json()` / `from_yaml()`. This deserialization
is a natural part of P2.7 (needed for `compare` to work) but could also be
deferred to P2.10 (baseline registry). **Recommendation**: Implement a
minimal `TestReport.from_dict()` classmethod in `schema.py`. This is a
small addition that serves P2.7 and P2.10.

### Where `evaluate()` Lives

**In `config.py`** — To keep `__init__.py` as a pure re-export surface
and avoid import-time side effects, `evaluate()` and its helpers
(`_resolve_suite_path`, `_load_baseline`) live in `config.py` and are
re-exported from `__init__.py`. This follows the pattern where
`__init__.py` is primarily a re-export surface.

**Final decision**: `evaluate()` lives in `config.py`, re-exported from
`__init__.py`. Helper functions (`_resolve_suite_path`, `_load_baseline`)
are private to `config.py`.

---

## 3. Public API Exports

### Owner's Proposal (from TODO.md)

> Export: `evaluate`, `EvalRunner`, `TestTask`, `TestReport`, `Score`

### Assessment: Correct, with additions

The five specified exports are the primary public API. We should also
export `TestConfig` (it's the point of this task) and `SuiteConfig` (the
suite definition that callers may want to inspect).

### Recommended `__all__`

```python
__all__ = [
  "__version__",
  "__author__",
  # Public API
  "evaluate",
  # Config
  "TestConfig",
  # Runner
  "EvalRunner",
  # Schema
  "TestTask",
  "TestReport",
  "Score",
  "SuiteConfig",
  # Report (for baseline comparison)
  "ComparisonReport",
]
```

### Export Rationale

| Export | Why |
|--------|-----|
| `evaluate` | Primary convenience function (FR11) |
| `TestConfig` | Config class for programmatic/CLI use |
| `EvalRunner` | Advanced: direct runner access for custom workflows |
| `TestTask` | Users construct tasks programmatically |
| `TestReport` | The return type of `evaluate()` — users inspect it |
| `Score` | Scorer return type — users implement custom scorers |
| `SuiteConfig` | Suite definition — users inspect loaded suites |
| `ComparisonReport` | Comparison result type — users inspect it |

**Not exported** (internal):
- `StatsCollector` — internal implementation detail
- `run_single_test` — legacy single-task function, not the public API
- `SCORERS` — registry, accessible via `yoker_test.scorers` if needed
- `load_suite`, `validate_suite` — available via `yoker_test.loader`
- `format_console_report`, `format_quality_ranking` — available via
  `yoker_test.report`

---

## 4. `TestReport.from_dict()` — Deserialization for Baselines

### Problem

`compare_baseline()` in `report.py` takes two `TestReport` objects.
`evaluate()` loads a baseline from a file (YAML/JSON dict). We need to
reconstruct `TestReport` from a dict.

### Design

Add a `from_dict()` classmethod to `TestReport` in `schema.py`:

```python
@classmethod
def from_dict(cls, data: dict) -> "TestReport":
  """Reconstruct a TestReport from a plain dict (e.g., loaded from YAML/JSON)."""
  run_data = data.get("run", {})
  run = RunMetadata(
    suite=run_data.get("suite", ""),
    suite_version=run_data.get("suite_version", ""),
    model=run_data.get("model", ""),
    provider=run_data.get("provider", ""),
    yoker_version=run_data.get("yoker_version", ""),
    temperature=run_data.get("temperature", 0.0),
    seed=run_data.get("seed", 0),
    repeats=run_data.get("repeats", 0),
    timestamp=run_data.get("timestamp", ""),
  )

  results = [TestResult(**_filter_fields(TestResult, r)) for r in data.get("results", [])]

  summary = {}
  for cat, s in data.get("summary", {}).items():
    summary[cat] = CategorySummary(**_filter_fields(CategorySummary, s))

  overall = None
  if data.get("overall"):
    overall = OverallSummary(**_filter_fields(OverallSummary, data["overall"]))

  comparison = None
  if data.get("comparison"):
    comp = data["comparison"]
    comparison = ComparisonReport(
      baseline=RunMetadata(**_filter_fields(RunMetadata, comp["baseline"])),
      delta=comp.get("delta", {}),
      flagged=comp.get("flagged", []),
    )

  return cls(
    run=run,
    results=results,
    summary=summary,
    overall=overall,
    comparison=comparison,
  )
```

With a private helper:

```python
def _filter_fields(cls: type, data: dict) -> dict:
  """Filter dict to only fields that exist on the dataclass."""
  return {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
```

This is a minimal, pragmatic deserializer. It handles missing keys with
defaults and ignores extra keys (forward/backward compatibility). It does
**not** handle type coercion or validation — the baseline file is assumed
to be a valid serialized `TestReport`. Full validation of baseline files
is P2.10's concern.

---

## 5. How `evaluate()` Gets a Yoker Config

### Three Paths

| Caller | Config Source | How |
|--------|--------------|-----|
| Library user (simple) | `get_yoker_config()` | `evaluate()` auto-loads |
| Library user (advanced) | Provided `TestConfig` | Passed via `config=` kwarg |
| CLI (P2.8) | `get_yoker_config()` or `TestConfig` from TOML | CLI constructs and passes |

### Design Decision: No `TestConfig` Auto-Construction

`evaluate()` does **not** construct a `TestConfig` internally. It accepts
`Config | None` — any `Config` subclass works. This is deliberate:

1. `TestConfig` adds fields like `suite`, `model`, `repeats` — these are
   already `evaluate()` parameters. Duplicating them on both the function
   signature and the config would create ambiguity.

2. `TestConfig` exists for CLI/TOML integration (P2.8), not for
   `evaluate()`. The function API is simpler with explicit parameters.

3. A caller who wants to use `TestConfig` can pass it:
   ```python
   config = TestConfig(suite="yoker_basic", model="glm-5.2:cloud")
   report = await evaluate(
     suite=config.suite,
     model=config.model,
     config=config,
   )
   ```
   The CLI (P2.8) will do exactly this.

### Config Application

When `config` is provided (or loaded), `evaluate()` sets the model on
the config before running:

```python
config.backend.config.model = model
config.backend.validate()
```

This is the same pattern used in `cli.py`'s `async_main()`. It ensures
the backend targets the requested model.

---

## 6. Module Structure

### `config.py` (new)

```
TestConfig(Config)           — config dataclass
_resolve_suite_path(suite)   — suite name → Path resolution
_load_baseline(path)         — load TestReport from YAML/JSON
evaluate(suite, model, ...)   — public async convenience function
```

### `__init__.py` (updated)

```
__version__, __author__      — existing
Re-exports from submodules   — public API surface
```

### `schema.py` (minor addition)

```
TestReport.from_dict(data)   — classmethod for deserialization
_filter_fields(cls, data)    — private helper for robust dict→dataclass
```

### Import Graph (no cycles)

```
__init__.py
  → config.py (evaluate, TestConfig)
    → yoker.config (Config, get_yoker_config)
    → loader.py (load_suite, validate_suite)
    → runner.py (EvalRunner)
    → report.py (compare_baseline)
    → schema.py (TestReport, and all dataclasses)
  → runner.py (EvalRunner)
  → schema.py (TestTask, TestReport, Score, SuiteConfig, ComparisonReport)
```

No module imports from `__init__.py`. All arrows point downward.

---

## 7. Test Strategy

### What to Test

1. **`TestConfig`**: Extends `Config`, has the right fields with correct
   defaults, can be instantiated without arguments.

2. **`evaluate()` orchestration**: Mock `EvalRunner.run()` and verify:
   - Suite is loaded from the right path
   - Runner is constructed with correct parameters
   - Model is set on config
   - Comparison is attached when `compare` is provided
   - Returns a `TestReport`

3. **`_resolve_suite_path()`**: Direct path, suite name, missing path.

4. **`TestReport.from_dict()`**: Round-trip `to_dict()` → `from_dict()`.

5. **`__init__.py` exports**: `from yoker_test import evaluate,
   EvalRunner, TestTask, TestReport, Score, TestConfig` all work.

### What NOT to Test

- `EvalRunner.run()` itself — already tested in `test_runner.py`
- `load_suite()` — already tested in `test_loader.py`
- Actual model execution — requires a live backend

### Test File

`tests/test_config.py` — tests for `TestConfig`, `evaluate()`, and
`_resolve_suite_path()`.

`tests/test_schema.py` — add `from_dict()` round-trip tests.

---

## 8. Acceptance Criteria Mapping

| Criterion | How Satisfied |
|-----------|-------------|
| `from yoker_test import evaluate, EvalRunner, TestTask, TestReport, Score` works | `__init__.py` re-exports all five |
| `await evaluate(suite="yoker_basic", model="glm-5.2:cloud")` returns `TestReport` | `evaluate()` in `config.py`, re-exported |
| `TestConfig` extends `yoker.Config` and is importable | `TestConfig(Config)` in `config.py` |
| Tests mock the runner and verify `evaluate()` orchestration | `tests/test_config.py` with mocked `EvalRunner.run` |
| Satisfies FR11 | `evaluate()` is the single-call public API |

---

## 9. P2.8 Forward Compatibility

`TestConfig` is designed for CLI integration in P2.8:

```python
# P2.8 will add @configclass decorator:
@configclass(cmd="eval", help="Run an evaluation suite")
class EvalConfig(TestConfig):
  """Config for `yoker-test eval` subcommand."""
  pass  # All fields inherited from TestConfig

# CLI usage:
# yoker-test eval --suite yoker_basic --model glm-5.2:cloud --repeats 5
```

The `output` field on `TestConfig` maps to the `--output` CLI arg. The
`compare` field maps to `--compare`. No changes to `TestConfig` will be
needed for P2.8 — just the `@configclass` decorator on a subclass.

---

## 10. Open Questions

1. **Baseline loading scope**: Should `TestReport.from_dict()` and
   `_load_baseline()` be fully implemented in P2.7, or should `compare`
   be accepted but raise `NotImplementedError` until P2.10?

   **Recommendation**: Implement now. The `from_dict()` classmethod is
   straightforward and the `compare` parameter is part of the acceptance
   criteria. Without it, `evaluate()` can't fulfill its contract when
   `compare` is provided.

2. **Suite directory convention**: Is `suites/{name}/suite.yaml` the
   convention, or `suites/{name}.yaml`?

   **Recommendation**: `suites/{name}/suite.yaml` — matches P2.9's
   description ("Create `suites/yoker_basic/` with 30-task suite YAML")
   and allows per-suite directories with additional resources (baseline
   files, configs, etc.).

---

## Action Items

1. **Create `src/yoker_test/config.py`**:
   - `TestConfig(Config)` dataclass with suite, model, compare, output, repeats fields
   - `_resolve_suite_path()` helper
   - `_load_baseline()` helper
   - `evaluate()` async function

2. **Update `src/yoker_test/__init__.py`**:
   - Re-export `evaluate`, `TestConfig`, `EvalRunner`, `TestTask`,
     `TestReport`, `Score`, `SuiteConfig`, `ComparisonReport`
   - Update `__all__`

3. **Add `TestReport.from_dict()` to `src/yoker_test/schema.py`**:
   - Classmethod for deserialization
   - `_filter_fields()` private helper

4. **Create `tests/test_config.py`**:
   - `TestConfig` field defaults and Config inheritance
   - `evaluate()` orchestration with mocked runner
   - `_resolve_suite_path()` resolution paths
   - `TestReport.from_dict()` round-trip

5. **Update `TODO.md`**: Mark P2.7 as complete after implementation.