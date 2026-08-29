# Design: Ollama Credit Usage Statistics + Score-Per-Cost Ranking (P2.5.10)

**Date:** 2026-08-30
**Task:** P2.5.10 (a+b+c+d) — capture Ollama credit usage per test and per run, persist it,
and add a score-per-cost composite to the quality ranking. Design only; no implementation.
**Related:** TODO.md P2.5.10; `research/ollama-credit-usage.md` (P2.5.10a);
`research/score-per-cost-formula.md` (P2.5.10c); `src/yoker_test/{schema,usage,runner,report,config,cli}.py`

---

## 1. Summary

Two snapshot layers, one formula:

- **Capture** (`EvalRunner.run()`): snapshot the Ollama usage API before and after every
  test execution (outside the timed section), gated on `provider == "ollama"`. The run-level
  aggregate delta reuses the first test's "before" and the last test's "after" — zero extra
  HTTP calls. Deltas land on `TestResult` (per test) and `OverallSummary` (aggregate).
- **Composite** (`report.py`): `rank_composite(report)` lifts the existing
  `compute_composite` shape to the summary level:
  `value = quality × 1/(1 + usage_session_delta / max(n_correct,1) × 1000)`.
  `summarize_overall` stores it on `OverallSummary.composite`; `format_quality_ranking`
  sorts by it, keeping raw session Δ and weekly Δ visible as columns.
- **No new classes.** One new public function in usage.py, one in report.py, small private
  helpers in runner.py. `compute_composite` is untouched.

Serialization needs no code changes (asdict dump / `_filter_fields` load already handle it).

---

## 2. Data model

### 2.1 `TestResult` (schema.py) — 2 new fields, appended at the end

| Field | Type | Default | Meaning |
|---|---|---|---|
| `usage_delta` | `dict[str, float] \| None` | `None` | Quota-fraction deltas around **this execution**: `{"session": Δ, "weekly": Δ}`. Keys are individually optional — an absent key means that window's delta was unavailable (window reset mid-test). `None` = usage tracking unavailable entirely (non-ollama provider, fetch failure, or missing snapshot pair). Values are fractions 0–1 (multiply ×100 only at display time). |
| `requests_delta` | `int \| None` | `None` | Exact per-model request-count delta (weekly window `limits.weekly.models[].request_count`) around this execution. The reliable per-test real metric; immune to quota quantization. `None` when unavailable. |

Rationale: the research's §5(a).1 offered flat fields (`usage_session_delta`, ...) or a
single mirror-dict. The mirror-dict wins — it matches `OverallSummary.usage_delta`, keys
already flow through `print_report`/ranking consumers, and fewer names is less surface.
`requests_delta` is separate because it is an `int` from a different part of the payload
and has different failure semantics (exact vs quantized).

Docstrings must state the noise caveat (§3.3 of the usage research): per-test quota deltas
are quantized at 3 decimals by the server (single light-model requests can round to 0.000);
treat as estimates. `requests_delta` is exact.

### 2.2 `OverallSummary` (schema.py) — 6 new fields, appended after `usage_delta`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `usage_delta` | `dict[str, float] \| None` | (exists) | Unchanged type; now actually populated with run-level `{"session": Δ, "weekly": Δ}`. Same partial-key rule: a window reset mid-run drops only that window's key. |
| `usage_note` | `str \| None` | `None` | Human-readable annotation when something poisoned the delta (window reset, snapshot unavailable). `None` when nothing notable — absence is the normal state for non-ollama runs. |
| `usage_before` | `dict[str, float] \| None` | `None` | Raw pre-run snapshot `{session, weekly}` fractions. Kept so a reset-poisoned delta can be audited/re-derived. |
| `usage_after` | `dict[str, float] \| None` | `None` | Raw post-run snapshot, same shape. |
| `requests_delta` | `int \| None` | `None` | Aggregate per-model request-count delta for the whole run (exact integer). |
| `extra_usage_cost_delta` | `float \| None` | `None` | Δ of `activity.cost` (extra-usage balance spend, USD), parsed from the API string. Only meaningful when the account draws from extra balance; `None` otherwise/unavailable. Not a token price — P2.6 territory stays untouched. |
| `composite` | `float \| None` | `None` | Score-per-cost value (§4). Always set by `summarize_overall` on fresh runs (equals `score` when usage unavailable). `None` = not computed (hand-built summaries, reports loaded from files written before P2.5.10). |

### 2.3 Backward compatibility

- All new fields have defaults and are appended last → positional construction of existing
  dataclasses keeps working; no existing constructor call breaks.
- Dump path (`to_dict` → asdict) serializes new fields automatically.
- Load path (`from_dict` → `_filter_fields`) drops unknown keys → old saved YAML/JSON files
  load with the new fields at their defaults, and *new* files load fine anywhere
  (forward-compatible readers, exactly the mechanism P2.1 already established).
- No CLI signature changes; `evaluate()` in config.py is unchanged.

---

## 3. Capture flow (runner.py)

### 3.1 Normalized snapshot

usage.py gets one new raw fetcher; the existing function becomes its extractor:

```python
# usage.py — new
async def fetch_ollama_usage_raw(config: Any) -> dict | None:
  """GET https://ollama.com/api/usage with the configured API key.

  Returns the full parsed JSON response, or None on missing ollama
  config/key or any request/parse failure (silent degradation, as today).
  """

# usage.py — refactor: fetch_ollama_usage keeps its exact current behavior
async def fetch_ollama_usage(config: Any) -> dict[str, float] | None:
  raw = await fetch_ollama_usage_raw(config)
  if raw is None:
    return None
  limits = raw.get("limits", {})
  return {
    "session": limits.get("session", {}).get("usage", 0.0),
    "weekly": limits.get("weekly", {}).get("usage", 0.0),
  }
```

The HTTP call then exists in exactly one place in yoker-test. Existing
`tests/test_usage.py` keeps passing (mocking `yoker_test.usage.httpx.AsyncClient` still
intercepts the single call site inside `fetch_ollama_usage_raw`).

### 3.2 Snapshot model in the runner

`EvalRunner` gains small private helpers:

```python
def _snapshot_usage(self, config: Any) -> dict[str, Any] | None:
  """One normalized usage snapshot, or None.

  Gate: provider must be "ollama" AND config.backend.ollama must exist with
  a non-empty api_key. Non-ollama runs never fetch (research §5(b).4).
  Returns {"session": f, "weekly": f, "requests": int, "extra_cost": f|None},
  where "requests" = limits.weekly.models[].request_count for this run's model
  (name match after stripping the ":cloud" suffix; absent → 0).
  """

def _usage_deltas(self, before, after) -> tuple[dict[str, float], int, float | None]:
  """Compute (usage_delta, requests_delta, extra_cost_delta) from two snapshots.

  - usage_delta: {"session": after-before, "weekly": after-before}, dropping
    any window whose delta is negative (window reset mid-run) — partial dict.
  - requests_delta: after.requests - before.requests; None if negative.
  - extra_cost_delta: after.extra_cost - before.extra_cost; None if either missing.
  """
```

Provider gate detail: check `getattr(config.backend, "provider", "") == "ollama"` at the
call site, then the existing `ollama_cfg.api_key` check inside `fetch_ollama_usage_raw`.
Both gates live in `_snapshot_usage` so callers can't bypass them.

### 3.3 Wiring in `EvalRunner.run()`

```python
async def run(self, model: str, config: Any) -> TestReport:
  config.backend.config.model = model

  before: dict[str, Any] | None = None   # run-level = first test's "before"
  results: list[TestResult] = []
  after: dict[str, Any] | None = None    # run-level = last test's "after"

  for task in self._tasks:
    for repeat in range(self._repeats):
      test_before = after if after is not None else None
      # "before" of the next execution is the "after" of the previous one;
      # nothing happens between executions, so this is exact and halves calls.
      if test_before is None:
        test_before = await self._snapshot_usage(config)
        if before is None and test_before is not None:
          before = test_before

      result = await self._execute_once(task, repeat, config)  # timing stays inside

      test_after = await self._snapshot_usage(config)
      after = test_after if test_after is not None else after

      usage_delta, requests_delta, _ = self._usage_deltas(test_before, test_after)
      result.usage_delta = usage_delta
      result.requests_delta = requests_delta
      results.append(result)
      ...  # existing progress print
```

Placement guarantees (research §5(a).2): snapshots happen strictly outside the timed
section — `_execute_once` takes `t0` *inside*, around `agent.process`. Latency, TTFT and
token metrics are unaffected.

Total HTTP cost: 2 calls per executed test × repeat (≈ 2×90 = 180 for the default
30×3 suite, each ~100ms, all outside timed sections — explicitly deemed reasonable use
in `research/ollama-credit-usage.md` §2.5). Run-level aggregate needs no extra calls:
`before` = first snapshot, `after` = last snapshot.

Aggregate assembly after the loop:

```python
usage_delta, requests_delta, extra_cost_delta = self._usage_deltas(before, after)
note: str | None = None
if self._gate_ok and before is None:
  note = "usage API unavailable"
elif usage_delta is missing-a-window:
  note = (f"{window} window reset mid-run "
          f"(before={before[window]:.4f}, after={after[window]:.4f})")

overall = summarize_overall(results, summary, self._weights, usage_delta=usage_delta)
overall.usage_note = note                      # annotations attached post-construction
overall.usage_before = {"session": ..., "weekly": ...} if before else None
overall.usage_after = {"session": ..., "weekly": ...} if after else None
overall.requests_delta = requests_delta
overall.extra_usage_cost_delta = extra_cost_delta
```

Keeping `summarize_overall`'s signature frozen (only `usage_delta`, already present)
avoids touching its caller contract and all its existing tests.

### 3.4 Error handling matrix

| Situation | Per test | Aggregate |
|---|---|---|
| Non-ollama provider / no key | Gate skipped; `usage_delta=None`, `requests_delta=None`; no HTTP, no note | same; columns render N/A |
| Fetch fails (network/timeout/4xx/5xx/shape change) | snapshot `None` → both fields `None`; run continues (never aborts the suite) | `usage_delta=None` + `usage_note="usage API unavailable"` |
| Negative window delta (reset mid-run) | that window's key dropped from the per-test dict | that window's key dropped; `usage_note` names the window with raw before/after |
| Both session and weekly reset | `usage_delta=None`, `requests_delta=None` | `usage_delta=None` + note |
| Quantized-to-zero delta (`0.000` rounding) | delta stored as `0.0` — a measured zero, not missing | `usage_delta={"session": 0.0, ...}`; `compute_composite` already maps `cost_delta <= 0` → `cost_score = 1.0` |
| Snapshot before OK, after fails (or vice versa) | `usage_deltas(None, x)` → `None`/`None` | note `"usage API unavailable"` |

Known limitation (documented, not engineered away): concurrent usage by other clients
inflates deltas; single-account benchmarking only.

### 3.5 Decision: extend `fetch_ollama_usage` vs raw variant vs yoker's `fetch_usage`

- **Adopt the raw variant** (`fetch_ollama_usage_raw`) with the existing function refactored
  on top of it: preserves the public shape and all 14 existing usage tests verbatim, gives
  access to `models[].request_count` and `activity.cost`, one HTTP call site.
- **Do not switch to yoker's `OllamaBackend.fetch_usage()`** (`../yoker/src/yoker/backends/ollama.py:66`).
  It returns the raw dict, which is *less* than our normalized snapshot needs, and using it
  would require instantiating an `OllamaBackend` — which mutates `os.environ["OLLAMA_API_KEY"]`
  and constructs an inference `AsyncClient` — just to make one metadata GET. It would also
  force the runner test-suite to stub a backend rather than an httpx client. The duplication
  (same URL, same header, 10s timeout) is accepted for testability and isolation; if Ollama
  changes the endpoint, the fix is one function in `usage.py`. Flagged here per the research's
  "a decision worth documenting" (§4.1).

---

## 4. Composite: score-per-cost

### 4.1 Formula — adopted verbatim from `research/score-per-cost-formula.md` §5 (Option E)

```text
value       = quality × cost_score
cost_score  = 1 / (1 + (usage_value / max(n_correct, 1)) × SCALE)

quality     = OverallSummary.score                        (0–1, weighted category mean)
usage_value = OverallSummary.usage_delta["session"]       (fraction 0–1; ×100 only for display)
n_correct   = quality × n_tasks,  n_tasks = len(report.results)
SCALE       = 1000.0   (parity with compute_composite's existing default)
```

Properties re-verified against the research: bounded [0,1]; strictly monotone
(↑quality ⇒ ↑value, ↑usage ⇒ ↓value); zero usage ⇒ `cost_score = 1.0` ⇒ value = quality
(no bonus for being free); `None` usage ⇒ same as zero usage; `n_correct < 1` ⇒
`cost_score = 1.0` (quality floor survives the zero-quality case). This is exactly the
existing `compute_composite` behavior — **no new formula, no new class**.

### 4.2 Placement in report.py

```python
def rank_composite(report: TestReport) -> float | None:
  """Score-per-cost composite (P2.5.10c): quality × 1/(1 + session-usage-per-correct × 1000).

  Returns the composite, or None when report.overall is missing.
  Delegates to compute_composite — the formula lives in exactly one place.
  """
```

Implementation: pull `quality = report.overall.score`, `usage_value =
report.overall.usage_delta.get("session")` (guard `usage_delta is None` → pass `None`),
`n_tasks = len(report.results)`, `n_correct = quality × n_tasks`; return `compute_composite(...)`.

Wrapper Check satisfied: a small free function reusing the existing formula — not a class,
not a configuration-forwarding shim.

### 4.3 Where the value lands

- **`summarize_overall`** computes and stores `overall.composite` via the same
  `compute_composite` call (quality = its own computed `score`, `usage_value` from its
  existing `usage_delta` param, `n_tasks = len(results)`), so freshly built reports persist
  the composite. The empty-results branch stores `composite=None`.
- **`format_quality_ranking`** does **not** read the stored `composite` — it calls
  `rank_composite(report)` on the fly, so reports saved before P2.5.10 (no stored composite)
  rank correctly too. The stored field exists for persistence/readers and the P2.10
  baseline registry.
- **`format_console_report`** gains two lines in the Overall section, right after `Usage Δ`:
  `Weekly Δ: {...}%` (when present) and `Composite: {x.xxxx}` (when not None).

### 4.4 Ranking output

New sort key and columns:

```text
Rank | Model | Quality | Std | Usage Δ (session) | Weekly Δ | Composite
```

- Sort: composite descending (`rank_composite`), then quality descending, then model name.
  With `usage_delta=None` on every report this degenerates exactly to the current
  quality-then-name ordering — existing ranking tests keep passing unchanged.
- Raw usage stays visible: session Δ column kept (as today, `N/A` when missing); weekly Δ
  column added as the "budget burn" companion (research §3 Option E: session drives the
  composite, weekly is secondary display only — do not feed it into the headline value).
- **Statistical ties**: a row whose composite is within `2 × max(own std, previous row's std)`
  of the previous row is flagged (append `≈` to the model cell) as a statistical tie.
  Ties are *flagged*, ranked by quality within the tie group — never by cheaper usage
  (research implementation note 4; the brief's own tie rule). Never rank models whose
  session deltas differ by less than the server's 0.001 quantization — their composites
  collapse to effectively equal and the tie flag shows it.

---

## 5. Persistence

No changes needed to any serialization code path:

- `TestReport.to_dict()` (asdict) picks up all new dataclass fields automatically →
  `to_yaml()` / `to_json()` persist `usage_delta`, `requests_delta` on both `TestResult`
  and `OverallSummary`, plus `usage_note`, `usage_before/after`,
  `extra_usage_cost_delta`, `composite`.
  Existing `_filter_fields`-based `from_dict` path (used by `--compare` baseline loading,
  cli.py) already tolerates both old files (missing keys → defaults) and new files.
- Field size impact: ≈ 2 floats per `TestResult` + 6 fields per report — negligible against
  the existing per-result payload (prompt, response, sub_scores).
- JSON compatibility: all values are `float`/`int`/`str`/`None` — no `default=str` hazards.

---

## 6. Test plan

### 6.1 New tests

**`tests/test_usage.py`** (extend; existing 14 keep passing):
- `fetch_ollama_usage_raw` success: full researched payload → raw dict returned (assert
  `limits.weekly.models[].request_count` and `activity.cost` survive round-trip).
- error paths: HTTP 403, `httpx.ConnectError`, `ReadTimeout`, JSON decode error,
  non-dict JSON body → all `None`.
- refactor regression: `fetch_ollama_usage` returns identical `{"session","weekly"}`
  extraction for the full payload (incl. missing `limits` → `{"session": 0.0, "weekly": 0.0}`).

**`tests/test_schema.py`**:
- `TestResult` / `OverallSummary` construct with new fields; defaults are `None`.
- round-trip: full report with new fields → `to_yaml` → `from_dict` values equal.
- old-file compat: a dict **without** the new keys reconstructs with defaults
  (`_filter_fields` drops unknown keys); a dict **with** the keys loads them.

**`tests/test_runner.py`** (new class `TestEvalRunnerUsageCapture`; patch
`yoker_test.runner`'s snapshot path):
- ollama + key: `overall.usage_delta == {"session": Δs, "weekly": Δw}` computed from mocked
  before/after snapshots; `overall.requests_delta` correct integer delta; raw
  before/after persisted; per-test results carry their `usage_delta`/`requests_delta`.
- provider gating: `provider="openai"` → snapshot helper never fetches (mock asserts zero
  calls); fields `None`.
- fetch failure (raw fetch returns `None`): suite completes; `usage_delta=None`;
  no crash.
- negative session delta (reset): `"session"` key absent from `usage_delta`, `"weekly"`
  present; `usage_note` mentions reset; composite unaffected (uses weekly-less session).
- per-test deltas quantized to 0.0: results get `{"session": 0.0, ...}`, not `None`.
- `overall.composite == rank_composite(report)` on a freshly built report.

**`tests/test_report.py`** (new tests; existing classes untouched):
- `rank_composite`: zero usage (`0.0`) → equals quality; `None` usage → equals quality;
  zero quality → 0.0 regardless of usage; zero `n_correct` (quality 0) → 0.0; single-task
  report (`n_tasks=1`, n_correct=quality) exact formula check
  `q / (1 + u/q × 1000)`; high usage devalues but stays ≤ quality; high quality + low usage
  beats low quality + low usage at equal absolute quality-gap.
- `summarize_overall`: sets `composite` consistent with `rank_composite` for the built
  report; empty-results branch → `composite is None`.
- `format_quality_ranking`: ordering by composite (a cheaper lower-quality model can pass a
  costlier equal-quality one); weekly Δ column rendered; `≈` tie flagging within 2×std;
  all-None usage → same ordering as today (guards existing tests); `N/A` rendering
  unaffected.

### 6.2 Existing tests that must not break — and the one helper tweak

- `TestComputeComposite*` (test_report.py): function signature and semantics unchanged.
- `TestFormatQualityRanking` existing 9 tests: all use `usage_delta=None` ⇒ composite ==
  quality ⇒ ordering identical (verified: sort-order, tie-break-by-name, single-report,
  usage-display tests pass unmodified).
- `TestSummarizeOverall.test_usage_delta_passthrough`: still passes (signature unchanged;
  only `composite` is added internally).
- `TestEvalRunnerRun` (test_runner.py): **`make_mock_config` gets one added line** —
  `config.backend.ollama = None`. Reason: a plain `MagicMock` makes
  `config.backend.ollama.api_key` auto-truthy, which would send real HTTP requests from
  unit tests. With `ollama=None` the provider gate short-circuits before any fetch. This
  changes a test helper, not test behavior/semantics.
- `test_usage.py` existing tests: unchanged — the refactor keeps the fetch inside the same
  module so `patch("yoker_test.usage.httpx.AsyncClient")` still intercepts it.
- test_cli.py / test_config.py: `evaluate()` and CLI untouched by this design.

`make check` (lint + typecheck + tests) is the gate.

---

## 7. Decisions on every "Required changes" item (research/ollama-credit-usage.md §5)

### (a) Per-test credit usage

| # | Research item | Decision |
|---|---|---|
| a.1 | New fields on `TestResult` (flat trio **or** mirror-dict) | **Adopt, adjusted**: mirror-dict `usage_delta` (matches `OverallSummary`, consumers already treat keys loosely) **plus** `requests_delta: int \| None`. Flat per-window floats rejected — two more names for data we may drop independently anyway. |
| a.2 | Snapshot around each `_execute_once`, outside timed section; "consider per task, not per repeat" | **Adopt placement; keep per-execution granularity.** One snapshot pair per task×repeat gives exact per-`TestResult` attribution, which is what the persistence criterion asks for. Volume (2×N calls) is explicitly within reasonable use (research §2.5). Consecutive executions share edges (next "before" = previous "after"), so effective extra calls = ~2×N, not 2×N+2. Revisit to per-task polling only if the suite grows past ~100 execs. |
| a.3 | Per-test quota deltas are noisy; request-count is the reliable one; persist raw snapshots "only if quantization auditing is desired" | **Adopt**: docstrings mark quota deltas as estimates; `requests_delta` documented as exact. Raw before/after persisted at the **aggregate** level only (`overall.usage_before/after`) — enough to audit resets without bloating 90 per-test results. |
| a.4 | Token-based per-test estimate from tokens × usage level | **Reject for P2.5.10** — deferred-pricing territory (P2.6, owner decision). Tokens stay visible in existing columns. |

### (b) Aggregate credit usage

| # | Research item | Decision |
|---|---|---|
| b.1 | Snapshot before/after loop; pass `usage_delta=` to `summarize_overall` ("(or evaluate() in config.py...)") | **Adopt; wire in `EvalRunner.run()`, not `evaluate()`**. Only the runner can reach the per-test loop where the same snapshots are needed; concentrating capture in one place keeps `evaluate()` a thin orchestrator (config.py stays unchanged). |
| b.2 | Negative delta → `usage_delta=None` + `usage_note` | **Adopt the note; adjust the None rule**: drop only the *poisoned window's* key instead of nulling the whole dict. A mid-run weekly reset must not erase a perfectly valid session delta — the composite reads `session`. Full reset ⇒ `None`. Recorded as a deviation, reason: needless data loss otherwise. |
| b.3 | Persist richer raw data: `usage_before/after`, `requests_delta`, `extra_usage_cost_delta`; extend `fetch_ollama_usage` or add raw variant | **Adopt all**: the four new `OverallSummary` fields (§2.2) + `fetch_ollama_usage_raw` (§3.1). `usage.py` gains no new HTTP path — raw fetch is the single call site; extraction helpers stay pure. |
| b.4 | Provider gate: only when `config.backend.provider == "ollama"` and a key is set | **Adopt**: explicit gate in `_snapshot_usage` (runner). Fixes the "stray ollama key + openai backend" hazard; the key-only check is now an inner defense layer. |
| b.5 | Decide session vs weekly for ranking display | **Adopt**: keep session as the composite driver (instantaneous suite cost); add weekly as a secondary display ("budget burn") + tie context only. Weekly is contaminated by non-run activity (research §3) — never the headline input. |
| — | Switch `usage.py` to yoker's `OllamaBackend.fetch_usage()` (duplication question, §4.1) | **No** — see §3.5. Duplication accepted for testability; single local call site; revisit only if the upstream endpoint changes. |

---

## 8. Open questions for the owner

1. **Per-test snapshot granularity** — I chose one snapshot pair per executed test
  (~180 GETs for the default 30×3 suite, tens of seconds of added wall time, all outside
  timed sections). Alternative: sparser per-task polling (research's own suggestion).
  Fine to keep per-execution?
2. **Stored vs on-the-fly composite** — design stores `OverallSummary.composite` for
  persistence/P2.10 while the ranking computes on the fly (old saved files rank correctly).
  Confirm you want the stored field at all (minimal-surface argument says on-the-fly only).
3. **Tie-break rule** — brief and research implementation note 4 say "break ties by
  quality only"; research §3's session/weekly paragraph once mentions breaking a session
  tie by the weekly composite. Design goes with quality-only. Confirm.
4. **`extra_usage_cost_delta` now vs with P2.6** — included since it is one parsed float
  from the same response; remove if you want the field surface stricter.
5. **Negative-delta handling deviation** — partial-dict (drop only the reset window)
  instead of the research's all-or-nothing `None`. Confirm consumers are OK with a
  `usage_delta` that may hold only `{"session": ...}` or `{"weekly": ...}`.

---

## 9. Action items (implementation order)

1. **usage.py**: add `fetch_ollama_usage_raw`; refactor `fetch_ollama_usage` onto it;
  add snapshot-normalization helper (`{"session","weekly","requests","extra_cost"}` from
  raw + model name, `:cloud` suffix stripped). Unit tests (§6.1).
2. **schema.py**: append new fields to `TestResult` and `OverallSummary` (§2). Construction
  + round-trip + old-file tests.
3. **runner.py**: `_snapshot_usage` / `_usage_deltas` private helpers; wire snapshots
  around `_execute_once` in `run()`; assemble aggregate `OverallSummary` annotations
  (§3.2–3.3). Update `make_mock_config` test helper. Runner capture tests (§6.1).
4. **report.py**: `rank_composite`; `summarize_overall` computes `composite`;
  `format_console_report` weekly/composite lines; `format_quality_ranking` new sort key,
  weekly column, `≈` tie flagging (§4). Formula + ranking tests (§6.1).
5. Commit per component; `make check` green at every step.

Explicitly out of scope: token-based pricing (P2.6 deferred), cookie-scraped settings page,
rendering changes beyond the table columns/lines above.