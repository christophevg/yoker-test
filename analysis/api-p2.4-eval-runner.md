# API Review: P2.4 — EvalRunner in runner.py

**Date**: 2025-01-20
**Reviewer**: API Architect Agent
**Task**: P2.4 — Implement EvalRunner class in runner.py

## Summary

This review covers the design of `EvalRunner`, the class that orchestrates
multi-task × multi-repeat evaluation through Yoker's SDK. It examines class
structure, three execution paths, per-repeat collection, TTFT measurement,
error handling, metadata collection, report assembly, backward compatibility,
and async considerations. The review concludes that **EvalRunner passes the
Wrapper Check** — it adds substantial orchestration logic beyond any single
Yoker SDK call.

---

## 1. EvalRunner Class Design

### Owner's Proposal (from TODO.md)

```python
class EvalRunner:
  def __init__(
    self,
    tasks: list[TestTask],
    repeats: int = 3,
    temperature: float = 0.0,
    seed: int = 42,
  )
  async def run(self, model: str, config: Any) -> TestReport
```

### Assessment: Works as specified

The `__init__` signature is correct. The parameters match `SuiteConfig`'s
repeats/temperature/seed fields, making it natural to construct an EvalRunner
from a loaded suite. The `run()` method returns `TestReport`, which is the
right top-level artifact.

**One concern**: `config: Any` is too vague. The actual parameter is a
`yoker.config.Config` instance. However, using `Any` is acceptable here
because yoker-test's `pyproject.toml` depends on yoker as an editable install,
and a concrete type annotation would create a hard import dependency from
runner.py to yoker's Config class. The current `run_single_test` also uses
`config: Any`. **Keep `Any` for consistency.**

### Recommended Full Signature

```python
class EvalRunner:
  def __init__(
    self,
    tasks: list[TestTask],
    repeats: int = 3,
    temperature: float = 0.0,
    seed: int = 42,
    suite_name: str = "",
    suite_version: str = "",
    aggregation_weights: dict[str, float] | None = None,
  ) -> None: ...

  async def run(self, model: str, config: Any) -> TestReport: ...
```

**Rationale for added `__init__` parameters**:

- `suite_name` / `suite_version`: Needed to populate `RunMetadata.suite` and
  `RunMetadata.suite_version`. Without these, `run()` would need them as
  additional parameters, which is worse — they describe the suite being run,
  not the runtime target. Passed at construction time from `SuiteConfig`.
- `aggregation_weights`: Needed for report assembly (P2.5's
  `aggregate_results` and `summarize_overall` consume these). Storing them on
  the runner avoids re-passing them to `run()`. Default `None` means uniform
  weighting.

These are data the runner needs to produce a complete `TestReport`. They are
not indirection — they are the suite's identity.

### Internal State

```python
self._tasks: list[TestTask]
self._repeats: int
self._temperature: float
self._seed: int
self._suite_name: str
self._suite_version: str
self._weights: dict[str, float] | None
```

The runner is stateless between `run()` calls — all per-run state (results,
metadata) is local to `run()`. This makes the runner reusable across models.

---

## 2. Three Execution Paths

### Functional Analysis (FR13, §10.6)

The functional analysis defines three paths:

| Path | Function | When | Why |
|------|----------|------|-----|
| Standard | `yoker.process()` | No tools, no system_prompt | Simplest one-shot |
| Tool-use | `yoker.agent()` + `agent.process()` | Task needs tools | Agent manages tool loop |
| Direct backend | `backend.chat_stream()` | Need TTFT or full control | Stream-level access |

### How to Detect Which Path a Task Needs

The current `TestTask` schema does not have an explicit `execution_path` or
`tools` field. Detection must be based on existing fields:

```python
def _select_path(self, task: TestTask) -> str:
  """Determine execution path from task attributes.

  Returns one of: 'process', 'agent', 'backend'.
  """
  # Tool-use tasks: scorer_config or task hints at tool usage.
  # This is deferred — no TestTask field currently signals tools.
  # For P2.4, all tasks go through 'agent' path (matches current
  # run_single_test behavior), with 'backend' path available when
  # TTFT collection is explicitly needed.
  if task.system_prompt is not None:
    return "agent"  # System prompt requires agent construction
  return "agent"  # Default — yoker.agent() with tools=None
```

**Concern**: The functional analysis describes `yoker.process()` as the path
for "standard tasks (no tools, no system prompt)". The current `run_single_test`
already uses `yoker.agent()` with `tools=None` and `system_prompt=None`, which
is functionally equivalent to `yoker.process()` but gives access to the event
stream via `StatsCollector`. Since `yoker.process()` internally calls
`yoker.agent()` (confirmed in api.py:313 — `built = agent(...); return await
built.process(prompt)`), using `yoker.agent()` directly is the right choice when
we need the event handler for metrics collection.

**Recommendation for P2.4**:

1. **Default path**: `yoker.agent(tools=None, event_handler=collector)` — same
   as current `run_single_test`. This gives us token/latency stats via
   `TurnEndEvent`. Use for all standard tasks.

2. **Backend path** (`backend.chat_stream()`): Use when TTFT measurement is
   needed. This requires direct access to the backend, obtained via
   `yoker.agent(backend=...).backend` or by constructing a backend from config.
   The streaming protocol yields `ChatChunk` events including
   `CONTENT_START`, `CONTENT_DELTA`, `USAGE`, `DONE`. TTFT = time from
   `chat_stream()` call to first `CONTENT_DELTA`.

3. **Tool-use path** (`yoker.agent(tools=[...])`): Deferred. No `TestTask` field
   currently declares required tools. When added (future task), the runner
   detects it and passes tool names. The event handler still works for metrics.

### Path Selection Strategy

```python
# P2.4 implementation: two paths active, one deferred
path = "backend" if self._need_ttft else "agent"

# Future (when TestTask.tools field is added):
# path = "agent_with_tools" if task.tools else "agent"
```

**The `yoker.process()` path is NOT needed separately.** It's a convenience
wrapper around `yoker.agent()` that we don't use because we need the event
handler. Document this in the code: we use `yoker.agent()` for all paths,
varying only `tools=` and `event_handler=`.

---

## 3. Per-Repeat Execution

### Task × Repeat Loop Structure

From §14 of the functional analysis:

```
For each task × repeat:
  → record start time
  → send prompt through Yoker
  → collect response, UsageStats, TTFT
  → score
  → assemble TestResult
  → handle errors
```

### Implementation

```python
async def run(self, model: str, config: Any) -> TestReport:
  results: list[TestResult] = []

  for task in self._tasks:
    for repeat in range(self._repeats):
      result = await self._execute_once(task, repeat, model, config)
      results.append(result)

  # Assemble metadata
  metadata = self._build_metadata(model, config)

  # Aggregate (deferred to P2.5, but EvalRunner must call it)
  # For P2.4: leave summary/overall empty; P2.5 fills them
  return TestReport(run=metadata, results=results)
```

**Key design decision: sequential, not concurrent.** Tasks run sequentially
because:

1. Most backends serialize concurrent calls on the same agent (confirmed in
   `yoker/core/__init__.py:320` — "Concurrent `process()` calls on the same
   agent are serialized via an internal `asyncio.Queue`").
2. Parallel calls to different agents would hit rate limits and produce
   non-comparable latency measurements.
3. The functional analysis (§14) describes a sequential loop, not parallel
   execution.

**The loop is task-major, repeat-minor**: all repeats of a task run
consecutively. This keeps per-task metrics grouped in the results list and
matches the execution loop diagram in §14.

### Per-Repeat TestResult

Each repeat produces a `TestResult` with `repeat` set to the repeat index
(0-based, matching the schema's convention):

```python
TestResult(
  task_id=task.id,
  category=task.category,
  score=score,
  response=response,
  extracted=extracted,
  tokens_in=tokens_in,
  tokens_out=tokens_out,
  latency_ms=latency_ms,
  thinking_chars=collector.thinking_chars,
  content_chars=collector.content_chars,
  error=error,
  difficulty=task.difficulty,
  repeat=repeat_idx,          # <-- the repeat index
  prompt=task.prompt,
  scorer_name=scorer_name,
  sub_scores=sub_scores,
  ttft_ms=ttft_ms,            # <-- from backend path, None for agent path
)
```

---

## 4. TTFT Collection

### When Streaming via `backend.chat_stream()`

The `ChatChunk` protocol (from `yoker/backends/protocol.py`) emits events in
order: `CONTENT_START` → `CONTENT_DELTA`* → `CONTENT_STOP` → `USAGE` → `DONE`.

TTFT is measured as wall-clock time from the start of `chat_stream()` iteration
to the first `CONTENT_DELTA` chunk:

```python
import time

async def _execute_via_backend(
  self, task: TestTask, backend: Any, model: str
) -> tuple[str, dict[str, Any], float | None]:
  """Execute via direct backend streaming. Returns (response, stats, ttft_ms)."""
  response_parts: list[str] = []
  thinking_parts: list[str] = []
  stats: dict[str, Any] = {}
  ttft_ms: float | None = None

  t0 = time.perf_counter()
  async for chunk in backend.chat_stream(
    model=model,
    messages=[{"role": "user", "content": task.prompt}],
  ):
    if chunk.event == ChatChunkEvent.CONTENT_DELTA:
      if ttft_ms is None:
        ttft_ms = (time.perf_counter() - t0) * 1000
      if chunk.text:
        response_parts.append(chunk.text)
    elif chunk.event == ChatChunkEvent.THINKING_DELTA:
      if chunk.text:
        thinking_parts.append(chunk.text)
    elif chunk.event == ChatChunkEvent.USAGE:
      if chunk.usage:
        stats["input_tokens"] = chunk.usage.input_tokens
        stats["output_tokens"] = chunk.usage.output_tokens
        stats["prompt_eval_count"] = chunk.usage.prompt_eval_count
        stats["eval_count"] = chunk.usage.eval_count
        stats["total_duration_ms"] = chunk.usage.total_duration_ms

  wall_ms = (time.perf_counter() - t0) * 1000
  return "".join(response_parts), stats, ttft_ms
```

### When NOT Streaming (agent path)

TTFT is `None`. The `StatsCollector` event stream does not expose per-chunk
timing — `CONTENT_CHUNK` events arrive but without reliable wall-clock markers
relative to prompt dispatch. Setting `ttft_ms = None` is correct and matches
the schema's `ttft_ms: float | None = None`.

### Concern: Accessing the Backend

To use `backend.chat_stream()`, we need a `ModelBackend` instance. Options:

1. **Via agent**: `yoker.agent(config=config, ...)` constructs an agent with a
   backend. Access via `agent.backend` (if exposed).
2. **Via config**: Construct directly from `config.backend`.

**Concern**: The `Agent` class may not expose its backend publicly. Looking at
the `yoker.agent()` factory: it accepts a `backend=` parameter, suggesting the
backend is a constructor argument, but whether it's accessible after
construction needs verification.

**Recommendation**: For P2.4, implement the backend path but mark it as
optional. The default path remains `yoker.agent()` with `StatsCollector`. TTFT
is collected only when the backend path is explicitly selected (e.g., via a
future `TestTask.execution_path = "backend"` field or a runner flag). This
keeps P2.4 simple and defers the backend-access question to when we actually
need TTFT.

**If the backend is not accessible from the agent, ask the user.** Per project
rules: don't guess or hack around Yoker limitations.

---

## 5. Error Handling

### Per-Task Errors (NFR5, FR16)

The current `run_single_test` already handles this correctly:

```python
error: str | None = None
try:
  response = await agent.process(task.prompt)
except Exception as exc:
  response = ""
  error = str(exc)
```

EvalRunner follows the same pattern but wraps the entire per-repeat execution:

```python
async def _execute_once(
  self, task: TestTask, repeat: int, model: str, config: Any
) -> TestResult:
  try:
    # ... execute via agent or backend ...
    # ... score ...
    return TestResult(..., error=None)
  except Exception as exc:
    return TestResult(
      task_id=task.id,
      category=task.category,
      score=0.0,
      response="",
      error=str(exc),
      repeat=repeat,
      prompt=task.prompt,
      difficulty=task.difficulty,
    )
```

**Key**: One task failure does NOT abort the suite. The outer loop continues
to the next task/repeat.

### Model Refusal Detection (FR16)

The functional analysis says:

> Record as error, score 0.0. Flag in report as "refused" if detected.

Detection heuristics:

1. **Empty response**: `response.strip() == ""` → likely refused.
2. **Safety filter patterns**: Response contains phrases like "I can't help
   with that", "I'm unable to assist", "I cannot provide". This is fragile —
   defer precise detection to P2.12 (as TODO.md already plans).

For P2.4, implement minimal refusal detection:

```python
def _detect_refusal(self, response: str, error: str | None) -> bool:
  """Minimal refusal detection. Full detection deferred to P2.12."""
  if error is not None:
    return False  # Error is a failure, not a refusal
  if not response.strip():
    return True  # Empty response likely means refusal
  return False
```

When detected, set `error = "refused"` and `score = 0.0`. The "refused" flag in
the TestResult can be stored in the `error` field as a string prefix:
`error = "refused: empty response"`. P2.12 will formalize this with a proper
flag.

---

## 6. RunMetadata Collection

### Fields to Collect

From `schema.py`:

```python
@dataclass
class RunMetadata:
  suite: str
  suite_version: str
  model: str
  provider: str
  yoker_version: str
  temperature: float
  seed: int
  repeats: int
  timestamp: str
```

### Where to Gather Each Field

| Field | Source | Access |
|-------|--------|--------|
| `suite` | `self._suite_name` | From `__init__`, passed from `SuiteConfig.suite` |
| `suite_version` | `self._suite_version` | From `__init__`, passed from `SuiteConfig.version` |
| `model` | `run()` parameter | The model string passed to `run(model=...)` |
| `provider` | `config.backend.provider` | `config.backend.provider` (str, defaults to `"ollama"`) |
| `yoker_version` | `yoker.__version__` | `import yoker; yoker.__version__` (confirmed: `"0.10.1"`) |
| `temperature` | `self._temperature` | From `__init__` |
| `seed` | `self._seed` | From `__init__` |
| `repeats` | `self._repeats` | From `__init__` |
| `timestamp` | `datetime.now()` | ISO format string |

### Implementation

```python
from datetime import datetime
import yoker

def _build_metadata(self, model: str, config: Any) -> RunMetadata:
  return RunMetadata(
    suite=self._suite_name,
    suite_version=self._suite_version,
    model=model,
    provider=getattr(config.backend, "provider", "unknown"),
    yoker_version=yoker.__version__,
    temperature=self._temperature,
    seed=self._seed,
    repeats=self._repeats,
    timestamp=datetime.now().isoformat(),
  )
```

**Note**: The `config.backend.provider` access is safe — `BackendConfig` has
`provider` as a required field with default `"ollama"`. The `getattr` fallback
is defensive for test mocks that may not set it.

---

## 7. TestReport Assembly

### P2.4 Scope vs P2.5 Scope

P2.4 is responsible for assembling the `TestReport` dataclass with results and
metadata. P2.5 implements the aggregation logic (`aggregate_results`,
`summarize_overall`, `compare_baseline`).

**P2.4 produces:**

```python
TestReport(
  run=metadata,
  results=all_results,       # list[TestResult], one per task×repeat
  summary={},                 # empty — P2.5 fills via aggregate_results()
  overall=None,               # None — P2.5 fills via summarize_overall()
  comparison=None,            # None — future baseline comparison
)
```

**P2.5 will add** (separate task, not P2.4's concern):

```python
report.summary = aggregate_results(results, self._weights)
report.overall = summarize_overall(results, report.summary, self._weights, usage_delta)
```

### Design Decision: Should EvalRunner call P2.5's functions?

**Yes, but only if they exist.** EvalRunner should attempt to call
`aggregate_results` and `summarize_overall` from `report.py` if available,
falling back to empty summary/overall if not yet implemented. This makes P2.4
forward-compatible with P2.5 without creating a hard dependency.

```python
# At the end of run():
from yoker_test.report import aggregate_results, summarize_overall  # if available

try:
  from yoker_test.report import aggregate_results, summarize_overall
  summary = aggregate_results(results, self._weights)
  overall = summarize_overall(results, summary, self._weights, usage_delta)
except ImportError:
  summary = {}
  overall = None
```

**Actually, simpler**: Since P2.4 and P2.5 are developed in sequence, just
import them directly. If P2.5 isn't done yet, the import fails and P2.4 leaves
them empty. But cleaner: don't import in a try/except. Just leave `summary={}`
and `overall=None` in P2.4 and let P2.5 wire up the aggregation call in the CLI
or a higher-level `evaluate()` function. This follows the simplicity principle.

**Final recommendation**: P2.4 returns `TestReport(run=metadata, results=results)`.
The `summary` and `overall` fields default to empty/None. P2.5 adds a
`post_process(report, weights, usage_delta)` function or the CLI calls
`aggregate_results` + `summarize_overall` after `run()`. Clean separation.

---

## 8. Backward Compatibility

### What Must Stay Working

1. **`StatsCollector`** — used by tests (`test_runner.py`) and by `run_single_test`.
2. **`run_single_test(task, config)`** — used by `cli.py` and tested in
   `test_runner.py`. Must remain a public async function with the same signature.
3. **All existing tests** — `test_runner.py` and `test_cli.py` must pass
   unchanged.

### Strategy

`EvalRunner` is **additive** — it sits alongside the existing functions. The
existing `run_single_test` and `StatsCollector` are not modified, not wrapped,
not deprecated. They remain the low-level primitives.

`EvalRunner._execute_once()` internally reuses the same pattern as
`run_single_test` (agent construction, StatsCollector, scoring) but is a
separate method — it does NOT call `run_single_test` because it needs to add
the `repeat` index, `prompt` field, `scorer_name`, and `difficulty` to the
TestResult (which `run_single_test` does not set).

**Potential refactor**: Extract a shared `_execute_and_score(task, model,
config, event_handler)` helper that both `run_single_test` and
`EvalRunner._execute_once` call. But per the simplicity principle, this adds
indirection for minimal gain — the functions are ~30 lines each. Keep them
separate. The duplication is acceptable.

### CLI Migration

`cli.py` currently calls `run_single_test` directly. After P2.4, the CLI
should construct an `EvalRunner` and call `run()`:

```python
# Future CLI (not P2.4's concern, but shows the intended use):
runner = EvalRunner(
  tasks=suite_config.tasks,
  repeats=suite_config.repeats,
  temperature=suite_config.temperature,
  seed=suite_config.seed,
  suite_name=suite_config.suite,
  suite_version=suite_config.version,
  aggregation_weights=suite_config.aggregation_weights,
)
report = await runner.run(model, config)
```

This is a CLI change, not a runner change. P2.4 does not touch `cli.py`.

---

## 9. Async Considerations

### `run()` is Async

`run()` is `async def` because it calls `await agent.process(prompt)` or
`await backend.chat_stream(...)`. This matches the existing `run_single_test`
which is also async.

### Event Loop

The caller (CLI or test) is responsible for the event loop:

```python
# CLI (current pattern in cli.py)
asyncio.run(async_main(model))

# Tests
@pytest.mark.asyncio
async def test_eval_runner():
  runner = EvalRunner(tasks=[...], repeats=2)
  report = await runner.run("model", mock_config)
```

EvalRunner does NOT manage its own event loop. It is a pure async class — call
it from within an async context. This is the correct pattern for a library
(versus a framework that manages its own loop).

### Concurrency Model

**Sequential execution within `run()`.** No `asyncio.gather()`, no task
pools. Each task×repeat runs one at a time. This ensures:

1. Latency measurements are not affected by concurrent requests.
2. Rate limits are not hit.
3. The agent's internal serialization queue (confirmed in
   `yoker/core/__init__.py:320`) is not a bottleneck.

**Future enhancement**: Optional concurrency could be added later via a
`max_concurrent` parameter, using `asyncio.Semaphore`. But for P2.4, sequential
is correct and simpler.

### AsyncClass / SyncClass Pattern

The API Architect agent definition requires async-first with Class/AsyncClass
naming for I/O-bound operations. However, `EvalRunner` is not a client
library — it's an evaluation orchestrator. The async-first with sync wrapper
pattern (like httpx's `Client`/`AsyncClient`) does not apply here because:

1. EvalRunner is called from `asyncio.run()` in the CLI — it's always in an
   async context.
2. There is no use case for a sync wrapper (the CLI already uses `asyncio.run`).
3. Adding a sync wrapper would mean running a background event loop in a
   thread, which is unnecessary complexity for a CLI tool.

**Decision**: `EvalRunner` is async-only. No `SyncEvalRunner` wrapper. This
follows the simplicity principle — the owner's proposal is async-only, and
there is no documented need for a sync interface.

---

## 10. Yoker SDK Interface Concerns

### `yoker.agent()` — Current Usage

The existing `run_single_test` uses:

```python
agent = yoker.agent(
  config=config,
  tools=None,
  system_prompt=None,
  console_logging=False,
  event_handler=cast(EventCallback, collector),
)
response = await agent.process(task.prompt)
```

This works. EvalRunner should use the same pattern, with two additions:

1. Pass `system_prompt=task.system_prompt` when the task has one.
2. The `config` should have `config.backend.config.model` set to the target
   model (as `cli.py` already does: `config.backend.config.model = model`).

**Concern**: The `config.backend.config.model` mutation is done in `cli.py`
before calling `run_single_test`. EvalRunner's `run()` receives `config` and
`model` separately. Should `run()` mutate `config.backend.config.model`?

**Yes, but carefully.** The current pattern in `cli.py`:

```python
config.backend.config.model = model
config.backend.validate()
```

EvalRunner should do the same at the start of `run()`:

```python
config.backend.config.model = model
# config.backend.validate()  # may raise — let caller handle
```

This is consistent with the existing pattern and necessary because the runner
receives `model` as a parameter, separate from `config`.

### `yoker.process()` — Not Used

As noted in §2, `yoker.process()` is a convenience wrapper that internally
creates an agent and calls `agent.process()`. We skip it because we need the
event handler for metrics collection. Document this clearly:

```python
# We use yoker.agent() directly (not yoker.process()) because we need
# the event_handler for StatsCollector to capture TurnEndEvent metrics.
# yoker.process() internally does the same thing but doesn't expose
# the event handler.
```

### `backend.chat_stream()` — Access Question

The `ModelBackend.chat_stream()` protocol (from `protocol.py:101`) yields
`ChatChunk` objects. To use it, we need a `ModelBackend` instance.

**How to get one**: `yoker.agent()` accepts a `backend=` parameter. If we pass
a pre-constructed backend, we can also use it for direct streaming. But the
agent factory constructs the backend internally when `backend=None`.

**To access the agent's backend**: Check if `Agent` exposes it. If not, we can
construct a backend independently from config. But this duplicates yoker's
internal backend construction logic.

**Recommendation**: For P2.4, do NOT implement the `backend.chat_stream()` path
fully. The agent path covers all current needs (metrics via events, scoring).
The backend path is needed only for TTFT, which is nullable in the schema. Leave
TTFT as `None` for all results in P2.4. When TTFT is needed, investigate backend
access — possibly by adding a `backend` property to `yoker.Agent` (a Yoker
modification, per project rules: ask the user first).

This is the simplest approach and passes the Wrapper Check: EvalRunner's value
is in the multi-step orchestration (task×repeat loop, error handling, metadata
collection, report assembly), not in TTFT measurement.

### Event Handler Compatibility

`StatsCollector` is typed as `EventCallback` via `cast`. The
`yoker.agent()` factory accepts `event_handler: EventCallback | None`.
`StatsCollector.__call__` is sync. Yoker's event system must support sync
callbacks — confirmed by the existing `run_single_test` working correctly.

**No change needed.** EvalRunner reuses `StatsCollector` as-is.

---

## Wrapper Check

**Question**: Does EvalRunner add real behavior beyond forwarding to
`yoker.process()` / `yoker.agent()`?

**Answer**: **Yes, EvalRunner passes the Wrapper Check.**

EvalRunner provides:

| Behavior | yoker.agent() alone | EvalRunner |
|----------|---------------------|------------|
| Single task execution | ✅ | ✅ (via agent) |
| Multi-task orchestration | ❌ | ✅ (loop over tasks) |
| Multi-repeat execution | ❌ | ✅ (task × repeat loop) |
| Per-repeat TestResult with repeat index | ❌ | ✅ |
| Error isolation (one task fails, suite continues) | ❌ | ✅ |
| Refusal detection | ❌ | ✅ (minimal) |
| RunMetadata collection | ❌ | ✅ (version, provider, timestamp) |
| TestReport assembly | ❌ | ✅ |
| Scorer resolution (string → function) | ❌ | ✅ (via scorers.py) |
| StatsCollector integration | Manual | ✅ (automatic) |

EvalRunner is not a thin wrapper — it's an orchestrator. The multi-step
loop, error isolation, metadata collection, and report assembly are
substantial logic that yoker.agent() does not provide.

---

## Findings

### Strengths

1. The existing `run_single_test` and `StatsCollector` provide a solid
   foundation — EvalRunner generalizes the same pattern to multi-task ×
   multi-repeat.
2. The schema (`TestResult`, `RunMetadata`, `TestReport`) already has all
   needed fields, including `repeat`, `ttft_ms`, `scorer_name`.
3. The `yoker.agent()` API with `event_handler` and `tools=None` is the
   right interface for standard evaluation tasks.

### Issues Found

#### Issue 1: `yoker.process()` path is redundant
- **Severity**: Low (design clarification)
- **Recommendation**: Document that EvalRunner uses `yoker.agent()` for all
  paths. `yoker.process()` is a convenience wrapper we don't need because we
  require the event handler.
- **Location**: This analysis document, runner.py docstring

#### Issue 2: Backend path access uncertain
- **Severity**: Medium (deferral)
- **Recommendation**: Defer `backend.chat_stream()` path and TTFT collection.
  P2.4 sets `ttft_ms = None` for all results. Investigate backend access as a
  separate task (possibly a Yoker modification).
- **Location**: runner.py — `_execute_once()` method

#### Issue 3: Config mutation in run()
- **Severity**: Low (existing pattern)
- **Recommendation**: EvalRunner.run() should set
  `config.backend.config.model = model` at the start, matching cli.py's
  existing behavior. This is not a new pattern — it's what the CLI already does.
- **Location**: runner.py — `run()` method

#### Issue 4: Refusal detection minimal
- **Severity**: Low (explicitly deferred)
- **Recommendation**: Implement only empty-response detection in P2.4.
  Full refusal detection is P2.12. Document the deferral.
- **Location**: runner.py — `_detect_refusal()` method

#### Issue 5: Aggregation deferred to P2.5
- **Severity**: Low (clean separation)
- **Recommendation**: P2.4 returns `TestReport` with `summary={}` and
  `overall=None`. P2.5 adds aggregation. The CLI or a higher-level `evaluate()`
  function wires them together.
- **Location**: runner.py — `run()` return statement

### Compliance Check

- **RESTful design**: N/A — this is an internal Python API, not HTTP.
- **Security**: N/A — no authentication/authorization in scope.
- **Documentation**: This analysis document satisfies the mandatory output
  requirement.
- **Simplicity principle**: EvalRunner is not over-engineered. It has one
  public method (`run()`), uses the existing `StatsCollector` and scorer
  infrastructure, and defers complex features (TTFT, tool-use, aggregation)
  to later phases.

---

## Recommended EvalRunner Implementation Outline

```python
class EvalRunner:
  """Orchestrates multi-task × multi-repeat evaluation through Yoker."""

  def __init__(
    self,
    tasks: list[TestTask],
    repeats: int = 3,
    temperature: float = 0.0,
    seed: int = 42,
    suite_name: str = "",
    suite_version: str = "",
    aggregation_weights: dict[str, float] | None = None,
  ) -> None:
    self._tasks = tasks
    self._repeats = repeats
    self._temperature = temperature
    self._seed = seed
    self._suite_name = suite_name
    self._suite_version = suite_version
    self._weights = aggregation_weights

  async def run(self, model: str, config: Any) -> TestReport:
    """Execute all tasks × repeats, return a TestReport."""
    config.backend.config.model = model

    results: list[TestResult] = []
    for task in self._tasks:
      for repeat in range(self._repeats):
        result = await self._execute_once(task, repeat, model, config)
        results.append(result)

    metadata = self._build_metadata(model, config)
    return TestReport(run=metadata, results=results)

  async def _execute_once(
    self, task: TestTask, repeat: int, model: str, config: Any
  ) -> TestResult:
    """Execute one task for one repeat. Errors don't propagate."""
    try:
      collector = StatsCollector()
      agent = yoker.agent(
        config=config,
        tools=None,
        system_prompt=task.system_prompt,
        console_logging=False,
        event_handler=cast(EventCallback, collector),
      )

      t0 = time.perf_counter()
      response = await agent.process(task.prompt)
      wall_ms = (time.perf_counter() - t0) * 1000

      # Normalize stats
      s = collector.stats
      tokens_in = s.get("input_tokens") or s.get("prompt_eval_count") or 0
      tokens_out = s.get("output_tokens") or s.get("eval_count") or 0
      latency_ms = s.get("total_duration_ms") or wall_ms

      # Detect refusal
      if not response.strip():
        return TestResult(
          task_id=task.id,
          category=task.category,
          score=0.0,
          response="",
          error="refused: empty response",
          difficulty=task.difficulty,
          repeat=repeat,
          prompt=task.prompt,
          tokens_in=tokens_in,
          tokens_out=tokens_out,
          latency_ms=latency_ms,
          thinking_chars=collector.thinking_chars,
          content_chars=collector.content_chars,
        )

      # Score
      scorer = task.scorer if callable(task.scorer) else SCORERS[task.scorer]
      score, extracted, sub_scores = normalize_score_result(scorer(task, response))
      scorer_name = task.scorer if isinstance(task.scorer, str) else getattr(
        task.scorer, "__name__", "custom"
      )

      return TestResult(
        task_id=task.id,
        category=task.category,
        score=score,
        response=response.strip(),
        extracted=extracted,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        thinking_chars=collector.thinking_chars,
        content_chars=collector.content_chars,
        error=None,
        difficulty=task.difficulty,
        repeat=repeat,
        prompt=task.prompt,
        scorer_name=scorer_name,
        sub_scores=sub_scores,
        ttft_ms=None,  # Deferred — requires backend.chat_stream() access
      )
    except Exception as exc:
      return TestResult(
        task_id=task.id,
        category=task.category,
        score=0.0,
        response="",
        error=str(exc),
        difficulty=task.difficulty,
        repeat=repeat,
        prompt=task.prompt,
      )

  def _build_metadata(self, model: str, config: Any) -> RunMetadata:
    """Collect run metadata from config and runner state."""
    return RunMetadata(
      suite=self._suite_name,
      suite_version=self._suite_version,
      model=model,
      provider=getattr(config.backend, "provider", "unknown"),
      yoker_version=yoker.__version__,
      temperature=self._temperature,
      seed=self._seed,
      repeats=self._repeats,
      timestamp=datetime.now().isoformat(),
    )
```

---

## Action Items

1. **Implement EvalRunner** as outlined above in `runner.py`, alongside
   existing `StatsCollector` and `run_single_test`.
2. **Write unit tests** (`tests/test_runner.py` additions): mock `yoker.agent()`,
   verify multi-task × multi-repeat execution, error isolation, metadata
   collection, repeat indices in TestResult.
3. **Verify backward compatibility**: all existing `test_runner.py` and
   `test_cli.py` tests pass unchanged.
4. **Defer TTFT**: set `ttft_ms = None` for all results in P2.4. Create a
   follow-up task for backend access investigation.
5. **Defer aggregation**: P2.4 returns `TestReport` with empty summary/overall.
   P2.5 fills them.
6. **Defer full refusal detection**: P2.4 detects only empty responses.
   P2.12 implements comprehensive detection.
7. **Document in runner.py docstring**: why `yoker.agent()` is used instead of
   `yoker.process()` (event handler access for metrics).

## Conclusion

**Approved** — the design is sound. EvalRunner passes the Wrapper Check with
clear orchestration value. The proposed implementation follows the owner's
specification from TODO.md with minimal additions (suite_name/version/weights
in `__init__`). TTFT, backend path, full refusal detection, and aggregation
are cleanly deferred to later phases.

## Next Steps

1. Implement EvalRunner in `runner.py` per this analysis.
2. Add tests in `tests/test_runner.py` for EvalRunner.
3. Run `make test` to verify all tests pass.
4. Proceed to P2.5 (aggregation and serialization) after P2.4 is committed.