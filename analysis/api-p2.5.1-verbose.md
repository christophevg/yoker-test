# P2.5.1: `--verbose` Flag for Full Per-Test Detail — Design Analysis

**Date**: 2026-08-31
**Task**: P2.5.1 — `--verbose` flag for full per-test detail (Simple)
**Reviewer**: API Architect Agent
**Related Documents**:
- `analysis/p2.5-report-aggregation.md` — P2.5 formatter design (style/decisions inherited here)
- `analysis/p2.8-cli-subcommands.md` — CLI subcommand layout
- `src/yoker_test/{cli,report,schema,runner}.py` — implementation surface reviewed

## Summary

`--verbose` on the `eval` subcommand (and the legacy `--model` path) switches the
console report's per-task section from one compact line per test to a full detail
block: complete untruncated prompt, exact raw response, and expected vs extracted
plus scorer, category, and score. No truncation of these fields.

**The only data gap is `expected`.** Audit of what `TestResult` already carries
(populated by `EvalRunner._execute_once` on all three return paths):

| Acceptance criterion | Field on `TestResult` | Status |
|---|---|---|
| complete untruncated prompt | `prompt` | present |
| exact raw response | `response` | present |
| expected | — | **missing** (lives on `TestTask`) |
| extracted | `extracted` | present |
| scorer | `scorer_name` | present (empty string on refusal/error paths — nothing was scored) |
| category | `category` | present |

Everything else verbose might show (tokens, latency, error, repeat, difficulty,
sub_scores) is already on the result. `--output` YAML/JSON serialization is
unaffected: `to_dict()` already serializes the full result.

## Design Decisions

### D1: Capture `expected` on `TestResult` (schema change)

**Decision**: Add `expected: Any = None` to `TestResult` and populate it in the
runner (`expected=task.expected` in all four `TestResult` constructions: three
paths in `_execute_once` plus `run_single_test`).

**Rationale**: The runner already copies task context onto results for reporting
purposes — `prompt`, `difficulty`, `scorer_name`. `expected` is the same pattern,
not a new one. Capturing it at execution time means the `TestReport` is
self-sufficient for audit: the formatter needs only the report (no task list
threading from `evaluate()` through `cmd_eval`), and saved reports (P2.5.2
always-save) will contain the expected answer alongside the response — closing
the same gap in the serialized output. The alternative (passing
`suite_config.tasks` to the formatter and joining on `task_id`) adds a parallel
data path through `evaluate()` and a join that can silently miss (generated
tasks, id mismatch) for zero benefit.

Placement at the end of the field list (after `requests_delta`) keeps positional
construction safe; all current constructions use kwargs. `Any` serializes fine
(`yaml.dump` natively; `json.dumps(default=str)` as fallback). Old baseline files
load unchanged via `_filter_fields` (missing key → default `None`).

### D2: Extend `format_console_report`, not a new top-level function

**Decision**: Add a keyword-only flag
`format_console_report(report, *, per_test_detail: bool = False) -> str`.
When `True`, the compact per-task line block is replaced by full detail blocks.
Header, category summaries, overall, and comparison sections are identical in
both modes.

**Rationale**: A separate `format_verbose_report` would duplicate the
header/summary/comparison formatting entirely to vary one ten-line section —
fails the simplicity/wrapper check. Default `False` keeps every existing call
site and test byte-identical. Only the per-task block differs.

### D3: Detail rendering as a pure helper

**Decision**: New public function
`format_test_detail(result: TestResult) -> list[str]` returning the block lines
for one result; `format_console_report(per_test_detail=True)` emits one block per
result inside the existing per-category grouping.

**Rationale**: Keeps the detail format unit-testable without wrapping a full
report, mirrors the existing `str`-returning formatter convention (formatters
return, callers print).

### D4: Block layout — no truncation, uniform indentation

**Decision**: Layout per test:

```
  ── R1 easy r0 ─ score=1.0  tokens=65+120  latency=2800ms ────────────
  Prompt:
    <full prompt, every line indented 4 spaces, verbatim>
  Response:
    <exact raw response, untruncated>
  Expected:   'b'
  Extracted:  'b'
  Scorer:     mcq
  Category:   reasoning
  Score:      1.0
  Sub-scores: <optional, key=value pairs — only when present>
  Error:      <error text — only when present>
```

- Header line reuses the compact-line fields (task id, difficulty, repeat,
  score, tokens, latency) so verbose blocks stay scannable.
- `Prompt:`/`Response:` headers plus 4-space indentation (`textwrap.indent`)
  make multi-line content visually fenced without adding markers that would
  corrupt the raw text. Nothing is truncated.
- `Scorer: (not scored)` when `scorer_name` is empty (refusal/error paths —
  scoring never ran); honest marker, not a blank.
- `Error:` line appended when `result.error` is set.
- Values use `!r` for `expected`/`extracted`, matching legacy `print_report`
  style (including `None` as `None`).

### D5: Explicitly out of scope (Simple budget)

- `system_prompt` display: lives on `TestTask`, not captured on the result;
  the spec's "assignment" is the prompt. Would require extending D1's pattern —
  separate decision if the owner wants it.
- Score `explanation` (on `Score`/result?): not in acceptance criteria; only the
  already-captured `sub_scores` surface.
- Any truncation policy for verbose content: none, per spec.
- `print_report` (legacy single-test full-detail printer, zero call sites in
  `src/`): untouched. Candidate dead code for a future cleanup, not here.

### D6: CLI wiring — two flags, distinct destinations

- `eval` subcommand: `eval_parser.add_argument("--verbose", action="store_true")`
  → `cmd_eval(..., verbose=args.verbose)`.
- Top-level parser: `parser.add_argument("--verbose", dest="legacy_verbose",
  action="store_true")` → passed to the legacy `cmd_eval` call. Distinct `dest`
  avoids the classic argparse wart where subparser defaults clobber the
  top-level namespace value. Documented as applying to the legacy `--model`
  path only.
- `cmd_eval` gains `verbose: bool = False` as last parameter (default keeps all
  existing callers valid) and does
  `print(format_console_report(report, per_test_detail=verbose))`.
- No change to `evaluate()` or `TestConfig`: verbose is presentation-only,
  applied after the report returns; `TestConfig` gains nothing (YAGNI).

## Function Specifications

### `format_test_detail` (report.py)

```python
def format_test_detail(result: TestResult) -> list[str]:
  """Return the verbose detail block lines for one test result."""
```

Emits the D4 layout. Empty prompt/response render as-is (empty fenced block);
empty `scorer_name` → `Scorer: (not scored)`; `sub_scores` and `error` lines
conditional.

### `format_console_report` (report.py, extended)

```python
def format_console_report(report: TestReport, *, per_test_detail: bool = False) -> str:
```

`per_test_detail=False` → byte-identical to today. `True` → per-task section
becomes `format_test_detail` blocks, grouped by category exactly as today;
all other sections unchanged (byte-identical to non-verbose output).

### `cmd_eval` (cli.py, extended)

```python
async def cmd_eval(
  suite: str, model: str, compare: str | None, output: str | None,
  repeats: int | None, with_paths: list[str] | None = None,
  verbose: bool = False,
) -> int:
```

## Console Ergonomics

30 tasks × 3 repeats = 90 detail blocks; verbose output on a full run is
inherently large — that is the point of the flag (no truncation, per spec).

- Suite progress stays on stderr (existing `[i/n] ...` lines), so
  `yoker-test eval ... --verbose > out.txt` captures only the report.
- The section order is unchanged: detail blocks sit at the top, summaries and
  overall at the bottom — `grep`/`sed -n` addressing by section label still
  works.
- Non-verbose output is unchanged; `--verbose` is opt-in per run.
- Files: `--output` already contains everything verbose shows (and now, via D1,
  `expected` too).

## Testing Strategy

Pure data construction, no Yoker mocking (house convention).

`tests/test_report.py`:
1. `format_test_detail` contains the full multi-line prompt (first and last
   distinctive lines both present — proves no truncation), exact response,
   expected, extracted, scorer, category, score.
2. Empty response → honest empty block; `scorer_name=""` → `(not scored)`.
3. `error` set → error line present; omitted otherwise.
4. `sub_scores` present → rendered; absent → no line.
5. `format_console_report(per_test_detail=True)`: blocks appear, compact lines
   do not; summaries/overall/comparison sections identical (string-equal) to
   the `per_test_detail=False` rendering.
6. `format_console_report(report)` default: unchanged output (guards the
   backward-compat claim).

`tests/test_cli.py`:
7. `eval --verbose` parses; dispatch passes `verbose=True` to `cmd_eval`
   (AsyncMock pattern from `test_p2_9.py`).
8. `--model X --verbose` (legacy) dispatches with `verbose=True`
   (`legacy_verbose` destination).
9. Integration: `cmd_eval` with `evaluate` patched to return a small report,
   `format_console_report` mocked → asserts `per_test_detail=True` when verbose,
   `False` otherwise.

## Action Items

1. `schema.py`: add `expected: Any = None` to `TestResult` (end of field list,
   with a one-line comment mirroring `prompt`'s "audit copy" rationale).
2. `runner.py`: populate `expected=task.expected` in all four `TestResult`
   constructions (three in `_execute_once`, one in `run_single_test`).
3. `report.py`: add `format_test_detail`; extend `format_console_report` with
   keyword-only `per_test_detail: bool = False`; emit blocks in the per-task
   section when set.
4. `cli.py`: `--verbose` on the eval parser; `--verbose` (dest
   `legacy_verbose`) on the top-level parser; thread through dispatch.
5. Tests per the strategy above (`tests/test_report.py`, `tests/test_cli.py`).
6. Run `make check` — all 415 existing tests must pass unaffected.

## Risks

| Risk | Mitigation |
|---|---|
| Argparse top-level/eval `--verbose` default collision silently drops the flag | Distinct `dest` (`legacy_verbose`); covered by CLI tests |
| `expected: Any` with exotic types in JSON output | `json.dumps(default=str)` fallback already in place; typical suites use strings |
| Old baselines lack `expected` | `_filter_fields` tolerates missing keys → `None` |
| Terminal flooding on large suites | Opt-in flag; stderr/stdout separation documented; no truncation is a spec requirement, not a defect |

## Conclusion

Approved for implementation. One additive schema field (D1) closes the only
data gap; the rest is a presentation flag on the existing formatter (D2–D4) and
three-line CLI wiring (D6). No open questions — the two deliberately deferred
items (`system_prompt`, score explanations) are recorded in D5 for a future
owner decision.