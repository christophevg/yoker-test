# API Analysis: P2.3 Loader Module

**Date**: 2025-07-23
**Task**: P2.3 — Implement `loader.py` for suite YAML loading
**Context**: Creating `src/yoker_test/loader.py` with `load_suite()` and `validate_suite()` functions. Resolves `!function` YAML tags to Python callables, supports dynamic task generation, per-suite scorer config overrides, and aggregation weights.
**Related**: `functional.md` (§6 Suite Format and Loading, FR3), `TODO.md` (P2.3 spec), `schema.py` (SuiteConfig, TestTask), `scorers.py` (SCORERS registry)

## Summary

The loader is a **two-function module** — `load_suite(path) -> SuiteConfig` and `validate_suite(config) -> list[str]`. No classes are needed. The `!function` tag resolution is a custom YAML constructor that imports modules and resolves attributes at parse time. Dynamic task generation happens post-parse if `task_generator` is present. Validation is a separate pass that returns a list of error strings (empty = valid).

**Wrapper Check**: No classes proposed. Both functions are standalone. No wrapper classes, no indirection. The design is as slim as it gets — two functions, one custom YAML constructor, one helper for `!function` resolution.

## 1. Module Structure

```
src/yoker_test/loader.py
├── _resolve_function(dotted_path: str) -> Callable
│   Import module, walk attribute path, return callable.
│   Raises ValueError with clear message on failure.
│
├── _function_constructor(loader, node) -> Callable
│   Custom YAML constructor for !function tag.
│   Extracts the dotted path string from the scalar node,
│   calls _resolve_function, returns the callable.
│
├── load_suite(path: str | Path) -> SuiteConfig
│   Main entry point. Reads file, parses YAML with custom
│   constructor, resolves task_generator, expands dynamic
│   tasks, applies scorer config overrides, maps aggregation
│   weights, constructs and returns SuiteConfig.
│
└── validate_suite(config: SuiteConfig) -> list[str]
    Validation pass. Checks required fields, scorer names,
    task ID uniqueness, generator output. Returns empty list
    if valid, list of error message strings if not.
```

**No classes.** Two public functions, two private helpers. This is the simplest structure that satisfies the requirements.

## 2. YAML Format Specification

The loader expects a YAML file with this structure:

```yaml
# --- Suite-level metadata (required) ---
suite: yoker_basic              # str, required
version: "1.0"                  # str, required
description: "..."               # str, required

# --- Runtime config (optional, has defaults) ---
repeats: 3                      # int, default: 3
temperature: 0.0                 # float, default: 0.0
seed: 42                         # int, default: 42
max_tokens: 4096                 # int | None, default: None

# --- Static tasks (used when no task_generator) ---
tasks:
  - id: K1                      # str, required
    category: knowledge          # str, required
    difficulty: easy             # str, optional (default: "")
    prompt: "..."                # str, required
    expected: "C"                # Any, required
    scorer: mcq                  # str | !function, required
    scorer_config:               # dict, optional (default: {})
      tolerance: 0.01
    system_prompt: "..."         # str | None, optional (default: None)

# --- Dynamic task generation (alternative to static tasks) ---
task_generator: !function code_suite.generate_tasks
generator_config:                # dict, optional (default: None)
  difficulty: [easy, medium, hard]
  count: 20

# --- Per-suite scorer config overrides (optional) ---
scorers:
  code_execution:
    timeout: 5
    sandbox: restricted

# --- Aggregation weights (optional) ---
aggregation:
  weights:
    knowledge: 0.25
    reasoning: 0.25
    instruction: 0.20
    code: 0.15
    tool_use: 0.15
```

### Field Mapping to SuiteConfig

| YAML field | SuiteConfig field | Notes |
|---|---|---|
| `suite` | `suite` | Required |
| `version` | `version` | Required |
| `description` | `description` | Required |
| `repeats` | `repeats` | Default: 3 |
| `temperature` | `temperature` | Default: 0.0 |
| `seed` | `seed` | Default: 42 |
| `max_tokens` | `max_tokens` | Default: None |
| `tasks` | `tasks` | Static tasks, or empty if using generator |
| `task_generator` | `task_generator` | Resolved callable or None |
| `generator_config` | `generator_config` | Dict or None |
| `aggregation.weights` | `aggregation_weights` | Dict or None |

### Scorer Config Overrides

The `scorers` section provides **default scorer_config overrides** that are merged into each task's `scorer_config`. Per-task `scorer_config` takes precedence. This is a merge, not a replace:

```python
# If suite has:
scorers:
  code_execution:
    timeout: 5

# And task has:
scorer: code_execution
scorer_config:
  test_cases: [...]

# Final scorer_config = {timeout: 5, test_cases: [...]}
# (suite-level defaults + task-level overrides)
```

**Design decision**: The `scorers` section in YAML maps scorer **names** to default config. When a task uses that scorer name, the suite-level defaults are merged in (task-level wins on conflict). This is a simple dict merge — no class needed.

## 3. `!function` Resolution Mechanism

### How It Works

PyYAML's custom constructor system handles `!function` tags:

```python
import importlib

def _resolve_function(dotted_path: str) -> Callable:
  """Resolve 'module.submodule.function' to a callable.

  Splits on '.', imports everything up to the last segment as a module,
  then getattr walks remaining segments.

  Examples:
    'yoker_basic.scorers.count_bullet_lines'
      → import yoker_basic.scorers; getattr(..., 'count_bullet_lines')

    'math.sqrt'
      → import math; getattr(math, 'sqrt')
  """
  parts = dotted_path.rsplit(".", 1)
  if len(parts) < 2:
    raise ValueError(
      f"!function expects 'module.path.function' notation, got: {dotted_path!r}"
    )

  module_path, attr_name = parts
  try:
    module = importlib.import_module(module_path)
  except ImportError as e:
    raise ValueError(
      f"!function could not import module {module_path!r}: {e}"
    ) from e

  try:
    return getattr(module, attr_name)
  except AttributeError as e:
    raise ValueError(
      f"!function: module {module_path!r} has no attribute {attr_name!r}"
    ) from e
```

### Registration with PyYAML

```python
import yaml

def _function_constructor(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> Callable:
  """YAML constructor for !function tags."""
  dotted_path = loader.construct_scalar(node)
  return _resolve_function(dotted_path)

# Register on a loader class (not global SafeLoader, to avoid side effects)
class SuiteLoader(yaml.SafeLoader):
  pass

SuiteLoader.add_constructor("!function", _function_constructor)
```

**Why a subclass of SafeLoader?** We avoid mutating the global `yaml.SafeLoader` which would affect all YAML parsing in the process. The subclass is local to the loader module. This is not a wrapper class — it's a standard PyYAML pattern for adding custom tags. It adds a constructor, it doesn't wrap and forward.

**Note on multi-segment paths**: The `rsplit(".", 1)` approach handles the common case of `module.function`. For deeper paths like `package.module.Class.method`, a more robust resolution would walk segments. However, the functional analysis (§6.3) specifies `module.path.function` notation, and lm-eval-harness uses the same simple `module.attr` pattern. We keep it simple. If needed later, the resolution can be extended to handle deeper paths.

**Revised approach for robustness**: Use `rsplit(".", 1)` for the module/attribute split. This handles `yoker_basic.scorers.count_bullet_lines` correctly: `importlib.import_module("yoker_basic.scorers")` then `getattr(module, "count_bullet_lines")`. This is the correct behavior — Python modules can have dots in their import path, and the final segment is the attribute name.

### Error Handling for `!function`

| Scenario | Error raised |
|---|---|
| Missing module | `ValueError` with "could not import module X" |
| Module exists but attribute missing | `ValueError` with "module X has no attribute Y" |
| No dot in path | `ValueError` with "expects module.path notation" |
| Empty string | `ValueError` with "expects module.path notation" |

All errors are raised **at load time** (during YAML parsing), not deferred. The error message includes the original dotted path for debugging.

### Call at Load Time?

The TODO says: "resolve `!function` tags to Python callables, call at load time, inject result". But looking at the functional analysis more carefully, there are **two distinct uses** of `!function`:

1. **Scorer references**: `scorer: !function my_suite.scorers.count_bullet_lines` → resolves to a callable, stored as `TestTask.scorer`. NOT called at load time — called during evaluation.

2. **Task generators**: `task_generator: !function code_suite.generate_tasks` → resolves to a callable, stored as `SuiteConfig.task_generator`. Called at load time with `generator_config` to produce `list[TestTask]`.

So `!function` always **resolves** to a callable. The "call at load time" part applies specifically to `task_generator` — that's the one that gets called with `generator_config` during loading to expand dynamic tasks. Scorer functions are stored as callables and invoked later during evaluation.

**This is the correct interpretation.** The `!function` constructor returns a callable. `load_suite` then decides what to do with it:
- If it's a `task_generator` → call it with `generator_config` → get `list[TestTask]`
- If it's a `scorer` → store the callable in `TestTask.scorer`

## 4. `load_suite` Flow

```
load_suite(path)
  │
  ├── 1. Resolve path to Path object
  │     - Accept str | Path
  │     - FileNotFoundError if not exists
  │
  ├── 2. Read file content
  │     - IOError/OSError propagates naturally
  │
  ├── 3. Parse YAML with SuiteLoader (custom !function constructor)
  │     - yaml.parse errors propagate as yaml.YAMLError
  │     - !function tags resolve to callables during parse
  │
  ├── 4. Extract suite-level fields
  │     - suite, version, description (required)
  │     - repeats, temperature, seed, max_tokens (optional, defaults)
  │     - aggregation.weights → aggregation_weights
  │     - scorers section → scorer_config_defaults dict
  │
  ├── 5. Resolve tasks
  │     - If task_generator present (callable):
  │       - Call task_generator(generator_config or {})
  │       - Expect list[TestTask] returned
  │       - If not list → ValueError
  │       - If items not TestTask → construct from dicts (see below)
  │     - Else: use static tasks from YAML
  │       - Each task dict → TestTask (with scorer resolution)
  │
  ├── 6. Apply scorer config overrides
  │     - For each task: if task.scorer is a string name in scorer_config_defaults,
  │       merge defaults into task.scorer_config (task wins on conflict)
  │
  ├── 7. Construct SuiteConfig
  │     - All fields populated
  │     - task_generator and generator_config preserved (for re-running)
  │
  └── 8. Return SuiteConfig
```

### Task Construction from YAML Dicts

Static tasks in YAML are dicts. The loader constructs `TestTask` from each:

```python
def _build_task(task_dict: dict, scorer_config_defaults: dict) -> TestTask:
  """Construct a TestTask from a YAML dict, applying scorer config defaults."""
  scorer = task_dict["scorer"]  # str or callable (from !function)

  # Merge suite-level scorer defaults with task-level config
  config = dict(scorer_config_defaults.get(
    scorer if isinstance(scorer, str) else "", {}
  ))
  config.update(task_dict.get("scorer_config", {}))

  return TestTask(
    id=task_dict["id"],
    category=task_dict["category"],
    prompt=task_dict["prompt"],
    expected=task_dict["expected"],
    scorer=scorer,
    difficulty=task_dict.get("difficulty", ""),
    system_prompt=task_dict.get("system_prompt"),
    scorer_config=config,
  )
```

### Dynamic Task Generator Output

When `task_generator` is called, it should return `list[TestTask]`. However, generators might return `list[dict]` for convenience. The loader handles both:

```python
generated = task_generator(generator_config or {})
if not isinstance(generated, list):
  raise ValueError(
    f"task_generator returned {type(generated).__name__}, expected list"
  )

tasks = []
for item in generated:
  if isinstance(item, TestTask):
    tasks.append(item)
  elif isinstance(item, dict):
    tasks.append(_build_task(item, scorer_config_defaults))
  else:
    raise ValueError(
      f"task_generator returned {type(item).__name__}, expected TestTask or dict"
    )
```

## 5. `validate_suite` Validation Rules

```python
def validate_suite(config: SuiteConfig) -> list[str]:
  """Validate a SuiteConfig. Returns list of error strings (empty = valid)."""
  errors: list[str] = []

  # 1. Required suite-level fields
  if not config.suite:
    errors.append("Suite field 'suite' is required and must not be empty")
  if not config.version:
    errors.append("Suite field 'version' is required and must not be empty")
  if not config.description:
    errors.append("Suite field 'description' is required and must not be empty")

  # 2. Must have tasks (either static or generated)
  if not config.tasks:
    errors.append("Suite has no tasks (neither static tasks nor task_generator output)")

  # 3. Task ID uniqueness
  seen_ids: set[str] = set()
  for task in config.tasks:
    if task.id in seen_ids:
      errors.append(f"Duplicate task ID: {task.id!r}")
    seen_ids.add(task.id)

  # 4. Each task has required fields
  for task in config.tasks:
    if not task.id:
      errors.append("Task missing required field: id")
    if not task.category:
      errors.append(f"Task {task.id!r} missing required field: category")
    if not task.prompt and not task.turns:
      errors.append(f"Task {task.id!r} missing required field: prompt (or turns)")
    if not task.scorer:
      errors.append(f"Task {task.id!r} missing required field: scorer")

    # 5. Scorer name exists in SCORERS (if it's a string)
    if isinstance(task.scorer, str):
      if task.scorer not in SCORERS:
        errors.append(
          f"Task {task.id!r} references unknown scorer: {task.scorer!r}. "
          f"Available: {', '.join(sorted(SCORERS.keys()))}"
        )
    elif not callable(task.scorer):
      errors.append(
        f"Task {task.id!r} scorer must be a string name or callable, "
        f"got: {type(task.scorer).__name__}"
      )

  return errors
```

### Validation Rule Summary

| Rule | Error message pattern |
|---|---|
| Empty `suite` | "Suite field 'suite' is required and must not be empty" |
| Empty `version` | "Suite field 'version' is required and must not be empty" |
| Empty `description` | "Suite field 'description' is required and must not be empty" |
| No tasks | "Suite has no tasks..." |
| Duplicate task ID | "Duplicate task ID: 'K1'" |
| Task missing `id` | "Task missing required field: id" |
| Task missing `category` | "Task 'K1' missing required field: category" |
| Task missing `prompt` | "Task 'K1' missing required field: prompt (or turns)" |
| Task missing `scorer` | "Task 'K1' missing required field: scorer" |
| Unknown scorer name | "Task 'K1' references unknown scorer: 'foo'. Available: ..." |
| Scorer not str/callable | "Task 'K1' scorer must be a string name or callable..." |

### Note on `turns` field (P2.16)

The validation checks `not task.prompt and not task.turns` — this is forward-compatible with the multi-turn conversation support (P2.16) where tasks can have `turns` instead of `prompt`. Since `TestTask` doesn't yet have a `turns` field, this check currently reduces to just `not task.prompt`. When P2.16 adds the `turns` field, the validation already handles it.

**Simpler approach for now**: Just check `not task.prompt`. When P2.16 lands, update the check. Don't over-engineer for a future task. Actually, since `getattr(task, 'turns', None)` works safely on a dataclass without that field, we can write it defensively. But that's adding complexity for YAGNI. Let's keep it simple: check `not task.prompt` now.

## 6. Error Handling Strategy

### Errors at Load Time (load_suite)

| Error | Exception | When |
|---|---|---|
| File not found | `FileNotFoundError` | `path` doesn't exist |
| Malformed YAML | `yaml.YAMLError` | YAML syntax invalid |
| Unresolvable `!function` | `ValueError` | Module import fails or attribute missing |
| Missing required suite field | `KeyError` | `suite`, `version`, or `description` absent from YAML |
| task_generator returns non-list | `ValueError` | Generator callable returns wrong type |
| task_generator returns invalid items | `ValueError` | Items are not TestTask or dict |

**Design**: `load_suite` raises exceptions for structural problems (file, YAML, `!function` resolution, missing required fields). It does NOT silently swallow errors. Validation of content (scorer names, ID uniqueness) is deferred to `validate_suite` — `load_suite` constructs the `SuiteConfig` even if it has issues, and the caller runs `validate_suite` to check.

**Rationale**: Separating construction from validation allows the caller to decide whether to abort on validation errors or just warn. The `show` subcommand can load and display a suite even with validation issues. The `eval` subcommand should call `validate_suite` and abort if errors exist.

### Errors at Validation Time (validate_suite)

`validate_suite` never raises. It returns a list of error strings. Empty list = valid. This makes it easy to accumulate all errors and report them together, rather than failing on the first one.

## 7. Edge Cases

### 7.1 Both `tasks` and `task_generator` present

**Decision**: `task_generator` takes precedence. If both are present, the generator output replaces static tasks. This matches the functional analysis (§6.4: "If task_generator present: call it → get tasks; else: use static tasks from YAML").

**Alternative considered**: Merge static + generated tasks. Rejected — this would make task ID uniqueness harder to reason about and the functional spec doesn't mention it.

### 7.2 `!function` in a `scorer` field vs `task_generator` field

The `!function` constructor resolves to a callable in both cases. The difference is what `load_suite` does with it:
- `scorer: !function foo.bar` → callable stored in `TestTask.scorer`, called during evaluation
- `task_generator: !function foo.bar` → callable stored in `SuiteConfig.task_generator`, called immediately with `generator_config`

### 7.3 `!function` pointing to a non-callable

`_resolve_function` returns whatever `getattr` returns. If someone writes `!function math.pi`, it resolves to `3.14159...`. The error surfaces when `load_suite` tries to call it (for `task_generator`) or when the runner tries to call it (for `scorer`). We could add a `callable()` check in `_resolve_function`, but that would be overly restrictive — some valid `!function` uses might resolve to objects with `__call__` that pass `callable()` but not `isinstance(x, types.FunctionType)`.

**Decision**: Don't check `callable()` in `_resolve_function`. Let the caller discover the type error naturally. This keeps the resolver generic.

### 7.4 Empty `generator_config`

If `generator_config` is absent from YAML but `task_generator` is present, call the generator with `{}`:

```python
generator_config = raw.get("generator_config") or {}
generated = task_generator(generator_config)
```

### 7.5 Suite with `scorers` section but no matching tasks

If the YAML has `scorers: { code_execution: { timeout: 5 } }` but no task uses `code_execution`, the defaults are simply unused. No error — the defaults are a lookup table, not a constraint.

### 7.6 `!function` with extra whitespace

`scorer: !function  foo.bar` — PyYAML's `construct_scalar` handles whitespace trimming. The dotted path will be `"foo.bar"`.

### 7.7 Circular or deeply nested `!function`

Not a concern — `!function` resolves to a Python callable by importing a module. There's no recursive YAML loading. The function itself might do anything at call time, but that's outside the loader's responsibility.

### 7.8 `aggregation.weights` absent

`aggregation_weights` defaults to `None`. The runner/report module handles `None` weights as equal weighting. No error.

## 8. Wrapper Check

**No classes proposed.** The module consists of:
- 2 private functions (`_resolve_function`, `_build_task`)
- 1 private YAML constructor (`_function_constructor`)
- 1 PyYAML loader subclass (`SuiteLoader`) — standard pattern for custom tags, not a wrapper
- 2 public functions (`load_suite`, `validate_suite`)

The `SuiteLoader` class is not a wrapper — it's the standard PyYAML mechanism for registering custom tag constructors. It adds a constructor, doesn't forward methods. This is idiomatic PyYAML, not an unnecessary abstraction.

**Verdict**: The design passes the wrapper check. No indirection, no forwarding classes, no unnecessary abstractions.

## 9. Dependency Check

The TODO says "Add `pyyaml` dependency to pyproject.toml". However, `pyyaml` is **already** in the dependencies:

```toml
dependencies = [
  "yoker>=0.10.1",
  "httpx>=0.25.0",
  "pyyaml>=6.0",
]
```

**Action**: No change needed. The dependency is already present. The `schema.py` module already imports `yaml` (for `TestReport.to_yaml()`).

## 10. Implementation Plan

### Step 1: Create `src/yoker_test/loader.py`

Implement the module as described above. The full function signatures:

```python
from collections.abc import Callable
from pathlib import Path

from yoker_test.schema import SuiteConfig, TestTask
from yoker_test.scorers import SCORERS

TaskGenerator = Callable[[dict], list[TestTask] | list[dict]]
```

### Step 2: Create `tests/test_loader.py`

Test cases:
1. **Valid static suite**: Load YAML with 3 static tasks, verify SuiteConfig fields
2. **Valid `!function` scorer**: Load YAML with `!function` scorer tag, verify callable stored
3. **Valid `task_generator`**: Load YAML with generator, verify tasks expanded
4. **`!function` unresolvable module**: Verify ValueError with clear message
5. **`!function` unresolvable attribute**: Verify ValueError with clear message
6. **`!function` missing dot**: Verify ValueError with "expects module.path notation"
7. **Missing file**: Verify FileNotFoundError
8. **Malformed YAML**: Verify yaml.YAMLError
9. **Missing required suite field**: Verify KeyError (suite/version/description)
10. **Duplicate task IDs**: validate_suite returns error
11. **Unknown scorer name**: validate_suite returns error
12. **Valid suite**: validate_suite returns empty list
13. **Scorer config merge**: Suite-level defaults merged with task-level config
14. **Both tasks and task_generator**: Generator takes precedence
15. **Empty generator_config**: Generator called with {}
16. **Aggregation weights**: Correctly mapped to aggregation_weights

### Step 3: Verify existing tests still pass

The loader is a new module — no existing code depends on it yet. Existing tests should be unaffected.

### Step 4: Commit

Use the c3:commit skill for an atomic commit.

## 11. Concerns

### 11.1 `SuiteLoader` subclass — is it a "class that wraps"?

No. It's the standard PyYAML pattern for custom tag constructors. `SuiteLoader(yaml.SafeLoader)` adds a constructor via `add_constructor()`. It doesn't wrap and forward — it extends the base class with new behavior. This is idiomatic, not an abstraction layer.

### 11.2 Should `load_suite` call `validate_suite` internally?

**No.** Keep them separate. The caller decides whether to validate. The `show` subcommand can load and display without validation. The `eval` subcommand should call both: `config = load_suite(path); errors = validate_suite(config); if errors: abort`.

### 11.3 Should `_build_task` be public?

**No.** It's an internal helper for constructing TestTask from YAML dicts. Users building suites programmatically construct TestTask directly. The helper exists only to bridge YAML dict → dataclass.

### 11.4 Security of `!function` — arbitrary code execution?

`!function` imports a Python module and gets an attribute. This is inherently trusting the YAML file — if you can write the YAML, you can reference `os.system`. This is the same trust model as lm-eval-harness. The YAML files are authored by the test suite creator, not by end users. **This is acceptable** — it's a developer tool, not a service handling untrusted input.

### 11.5 `max_tokens` field

`SuiteConfig` has `max_tokens: int | None = None`. The YAML format supports it as an optional field. The loader maps it directly. No special handling needed.

## 12. Action Items

- [ ] Implement `src/yoker_test/loader.py` (two functions + helpers as described)
- [ ] Create `tests/test_loader.py` with all 16 test cases listed in §10
- [ ] Verify `pyyaml` dependency (already present — no change needed)
- [ ] Run `make test` to verify all existing tests still pass
- [ ] Run `make check` for lint/type/format compliance
- [ ] Commit using c3:commit skill