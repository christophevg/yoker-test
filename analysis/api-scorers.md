# API Analysis: P2.2 Scorers Module

**Date**: 2025-07-22
**Task**: P2.2 — Implement additional scorers in `scorers.py`
**Context**: Adding `normalize_response`, 6 new scorers, updating `mcq_scorer` to 6-stage fallback, changing return type from `tuple[float, str | None]` to `float | Score`
**Related**: `../yoker/analysis/yoker-test-analysis.md` (architecture), `TODO.md` (P2.2 spec)

## Summary

This review covers the scorer API design for P2.2. The core design decision is the return type change from `tuple[float, str | None]` to `float | Score`, which has a ripple effect on `runner.py`, `test_scorers.py`, and `test_runner.py`. The `normalize_response` utility should follow the simple-evals ordering exactly. The `code_execution` scorer needs careful sandboxing. The 6-stage MCQ fallback has a meaningful progression from specific to general extraction.

## Design Review

### 1. Scorer Signatures: `float | Score` Return Type

**Recommendation: Use `float | Score` as specified.** This is the right design.

The union type lets simple scorers (mcq, exact_match, contains, json_valid) return a bare `float` — no need to construct a `Score` object when there's nothing beyond the value. Complex scorers (code_execution) return `Score` with `sub_scores` and `explanation`.

**Alternative considered**: Always return `Score`. Rejected — it adds boilerplate to every simple scorer (`return Score(value=1.0)` instead of `return 1.0`) with no benefit. The `Score` dataclass exists for when extra metadata is needed; forcing it everywhere violates the simplicity principle.

**Impact on runner.py** (current code):
```python
# Current — breaks with float | Score
score, extracted = scorer(task, response)

# Must become:
result = scorer(task, response)
if isinstance(result, Score):
  score = result.value
  extracted = result.extracted
  sub_scores = result.sub_scores
else:
  score = result
  extracted = None
  sub_scores = None
```

**Recommendation**: Add a `normalize_score_result` helper in `scorers.py`:

```python
def normalize_score_result(result: float | Score) -> tuple[float, str | None, dict[str, float] | None]:
  """Convert float | Score to (value, extracted, sub_scores)."""
  if isinstance(result, Score):
    return result.value, result.extracted, result.sub_scores
  return result, None, None
```

This keeps the unpacking logic in one place. The runner calls `normalize_score_result(scorer(task, response))` and gets a clean tuple. The `TestResult` fields `score`, `extracted`, and `sub_scores` are populated from this tuple.

### 2. Impact on Existing Code

| File | Current | After P2.2 | Change Required |
|------|---------|------------|-----------------|
| `scorers.py` | `mcq_scorer` returns `tuple[float, str \| None]` | All scorers return `float \| Score` | Rewrite `mcq_scorer`, add new scorers, add helper |
| `runner.py` | `score, extracted = scorer(task, response)` | Use `normalize_score_result()` | Small change in `run_single_test` |
| `report.py` | Reads `result.score`, `result.extracted` | No change | None — operates on `TestResult`, not scorer output |
| `cli.py` | Calls `run_single_test` | No change | None — operates on `TestResult` |
| `test_scorers.py` | Unpacks `score, extracted = mcq_scorer(...)` | Must handle `float \| Score` | All tests updated: simple scorers return float, unpack differently |
| `test_runner.py` | Checks `result.score`, `result.extracted` | No change if runner handles conversion | None — tests check `TestResult` fields, not scorer output |

**Key insight**: The return type change is contained to `scorers.py` and `runner.py`. `report.py` and `cli.py` are unaffected because they operate on `TestResult`, which already has `score`, `extracted`, and `sub_scores` as separate fields. The runner is the adapter between scorer output and `TestResult`.

### 3. `normalize_response` Implementation

**Source**: [openai/simple-evals `common.py`](https://github.com/openai/simple-evals/blob/main/common.py)

The simple-evals implementation is a chain of `.replace()` calls. The ordering matters critically:

```python
def normalize_response(response: str) -> str:
  return (
    response
    .replace("**", "")          # 1. Bold markdown
    .replace("$\\boxed{", "")    # 2. LaTeX boxed prefix (before $ and {)
    .replace("}$", "")           # 3. LaTeX boxed suffix (before $)
    .replace("\\$", "")          # 4. Escaped dollar signs (before $)
    .replace("$\\text{", "")     # 5. LaTeX text prefix (before $ and {)
    .replace("$", "")            # 6. Remaining dollar signs (after all $-patterns)
    .replace("\\mathrm{", "")    # 7. LaTeX mathrm (before \{ and {)
    .replace("\\{", "")          # 8. Escaped braces (before {)
    .replace("\\text", "")        # 9. Remaining text command
    .replace("\\(", "")          # 10. LaTeX inline open
    .replace("\\mathbf{", "")    # 11. LaTeX mathbf (before {)
    .replace("{", "")            # 12. Remaining braces (after all {-patterns)
    .replace("\\boxed", "")      # 13. Remaining boxed command
  )
```

**Why ordering matters**:

| Step | Why it must come before | Reason |
|------|------------------------|--------|
| 2 (`$\boxed{`) | 6 (`$`) | If `$` is removed first, `$\boxed{` loses its `$` and won't match |
| 3 (`}$`) | 6 (`$`) | If `$` is removed first, `}$` loses its `$` and won't match |
| 4 (`\$`) | 6 (`$`) | `\$` must be handled before bare `$` removal |
| 5 (`$\text{`) | 6 (`$`) and 12 (`{`) | Both `$` and `{` would break the pattern if removed first |
| 7 (`\mathrm{`) | 8 (`\{`) and 12 (`{`) | `{` inside `\mathrm{` would be consumed by step 12 |
| 8 (`\{`) | 12 (`{`) | Escaped brace must be handled before bare brace |
| 11 (`\mathbf{`) | 12 (`{`) | Same as `\mathrm{` |
| 13 (`\boxed`) | — | Last because earlier steps removed all `\boxed{` instances; this catches bare `\boxed` without `{` |

**Recommendation**: Copy the simple-evals ordering exactly. It's battle-tested. Do not reorder or "optimize" the chain. Add a docstring noting the ordering dependency.

### 4. `code_execution` Scorer: Sandboxing and Security

This is the highest-risk scorer. It executes arbitrary model-generated code.

**Threat model**: The model output is untrusted. Code could attempt file I/O, network access, infinite loops, or memory exhaustion.

**Sandboxing approach**:

```python
def code_execution(task: TestTask, response: str) -> float | Score:
  code = _extract_code(response)
  if not code:
    return 0.0

  timeout = task.scorer_config.get("timeout", 5)
  test_cases = task.scorer_config.get("test_cases", [])

  restricted_globals = {
    "__builtins__": {
      # Safe builtins only
      "print": print, "len": len, "range": range, "int": int,
      "float": float, "str": str, "list": list, "dict": dict,
      "tuple": tuple, "set": set, "bool": bool, "abs": abs,
      "min": min, "max": max, "sum": sum, "sorted": sorted,
      "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
      "round": round, "isinstance": isinstance, "type": type,
      "True": True, "False": False, "None": None,
      "Exception": Exception, "ValueError": ValueError,
      "TypeError": TypeError, "IndexError": IndexError,
      "KeyError": KeyError, "ZeroDivisionError": ZeroDivisionError,
    }
  }

  results = {}
  passed = 0
  for i, tc in enumerate(test_cases):
    key = f"case_{i}"
    try:
      local_ns: dict = {}
      exec(code, dict(restricted_globals), local_ns)
      # Test case format: {"func": "solution", "args": [1, 2], "expected": 3}
      func_name = tc.get("func", "solution")
      func = local_ns.get(func_name)
      if func is None or not callable(func):
        results[key] = 0.0
        continue
      args = tc.get("args", [])
      expected = tc.get("expected")
      actual = func(*args)
      if actual == expected:
        results[key] = 1.0
        passed += 1
      else:
        results[key] = 0.0
    except Exception:
      results[key] = 0.0

  total = len(test_cases)
  value = passed / total if total > 0 else 0.0
  return Score(value=value, sub_scores=results, explanation=f"{passed}/{total} cases passed")
```

**Timeout handling**: Python's `signal.alarm()` is Unix-only and doesn't work with `exec` reliably (the signal is only delivered to the main thread). Options:

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| `signal.alarm()` | Simple, built-in | Unix-only, doesn't interrupt `exec` mid-statement | ❌ Not reliable |
| `threading.Timer` + interrupt | Cross-platform | Can't safely kill a thread in Python | ❌ Thread can't be killed |
| `multiprocessing` + `join(timeout)` | Can kill process | Heavier, needs pickling | ✅ Best option |
| Skip timeout, rely on restricted builtins | Simple | Infinite loops still hang | ❌ Unsafe |

**Recommendation**: Use `multiprocessing.Process` with `join(timeout)`. If the process is still alive after timeout, `terminate()` it. This is the only reliable way to enforce a timeout on `exec()` in Python.

However — for P2.2, a simpler approach may be acceptable initially: use `signal.alarm()` with a note that it's Unix-only, or use `multiprocessing` with a `timeout` config. The TODO says "exec in sandbox with `timeout` config" — the implementation detail is left to us.

**Pragmatic recommendation**: Start with `signal.alarm()` for simplicity (the project runs on macOS/Linux), document the Unix-only limitation, and note `multiprocessing` as a future hardening step. This follows the simplicity principle.

**Security considerations**:
- Restricted `__builtins__` prevents `open()`, `exec()`, `eval()`, `__import__()`, `compile()`
- No `import` statement will work (no `__import__` in builtins)
- File I/O blocked (no `open`)
- Network blocked (no `socket` import possible)
- The restricted builtins list should be explicitly documented as the security boundary
- **This is not a true sandbox** — determined attackers can escape restricted `exec` via attribute traversal (e.g., `().__class__.__bases__[0].__subclasses__()`). For a model eval framework, this risk is acceptable since we control the prompts, but it should be documented.

### 5. `mcq_scorer` 6-Stage Fallback

**Current 4 stages**:
1. Exact A-D (full response stripped)
2. `Answer: B` pattern (full response)
3. First standalone `\b[ABCD]\b` (full response)
4. `^([ABCD])\)` paren pattern (start of response)

**New 6 stages**:
1. Exact A-D (same)
2. `Answer: B` pattern (same)
3. `\b[ABCD]\b` on **first line only** (NEW — restricted scope)
4. `^([ABCD])\)` paren pattern (same as current stage 4)
5. First standalone `\b[ABCD]\b` on **full response** (same as current stage 3, but demoted to fallback)
6. No match → 0.0

**Analysis of stage 3 vs stage 5**:

| Stage | Scope | Intent |
|-------|-------|--------|
| 3 | First line only | Model puts answer at the start, before reasoning |
| 5 | Full response | Model buries answer in reasoning text — last resort |

This is a **correct progression**: specific → general. Stage 3 catches the common pattern where the model says "B\nLet me explain..." — the answer is clearly B. Stage 5 is the fallback for verbose responses where the letter appears somewhere in the text.

**Concern: Is stage 3 different enough from stage 5 to be a separate stage?**

Yes. Consider: "The answer is clearly D because..." — stage 3 would NOT match if "The answer is clearly D" is the first line (it would match `D` via `\b[ABCD]\b`). But stage 5 would also match. The difference is:

- Stage 3: `text.split('\n')[0]` searched with `\b[ABCD]\b` — high confidence, first line
- Stage 5: full `text` searched with `\b[ABCD]\b` — low confidence, anywhere

The practical difference: if the first line is "Let me think about this carefully" (no letter), stage 3 skips. Stage 5 then searches the full text and might find "The answer is C" in line 5. This avoids false positives where a letter in the first line is not the answer but a step in reasoning.

**Wait — there's a subtlety.** Stage 3 would match `A` in "A more detailed analysis..." — `A` is a standalone word boundary match. This is a false positive. The current stage 3 (which is the same regex on the full text) has the same problem but worse — it searches everything.

**Recommendation**: The progression is correct. Stage 3 on the first line is more precise than stage 5 on the full text. Both have false positive risk, but stage 3 has less surface area. The ordering (3 before 5) ensures we try the more precise match first.

**Note on stage 4 regex**: The TODO writes `^([ABCD])` but describes it as "paren pattern". The current code uses `^([ABCD])\)` (with the closing paren). I recommend keeping the `)` in the regex: `^([ABCD])\)`. This matches "C) Paris" but not "C is the answer". Without the `)`, it would match any response starting with A-D, which is too broad and would conflict with stage 1 (exact match).

### 6. `SCORERS` Dict Type Annotation

**Current**:
```python
SCORERS: dict[str, Callable[[TestTask, str], tuple[float, str | None]]] = {"mcq": mcq_scorer}
```

**New**:
```python
from yoker_test.schema import Score

ScorerResult = float | Score
ScorerFunc = Callable[[TestTask, str], ScorerResult]

SCORERS: dict[str, ScorerFunc] = {
  "mcq": mcq_scorer,
  "exact_match": exact_match,
  "numeric_match": numeric_match,
  "regex_extract": regex_extract,
  "contains": contains,
  "json_valid": json_valid,
  "code_execution": code_execution,
}
```

**Recommendation**: Define type aliases (`ScorerResult`, `ScorerFunc`) for readability. This makes function signatures and the registry cleaner than inlining `Callable[[TestTask, str], float | Score]` everywhere.

### 7. `scorer_config` Access Pattern

Each scorer reads its configuration from `task.scorer_config` (a `dict` with `field(default_factory=dict)`).

**Pattern**:
```python
def exact_match(task: TestTask, response: str) -> float | Score:
  ignore_case = task.scorer_config.get("ignore_case", False)
  ignore_punctuation = task.scorer_config.get("ignore_punctuation", False)
  # ...
```

**Concerns**:
- **Missing config**: `dict.get(key, default)` handles this cleanly. No validation needed — missing keys use defaults.
- **Malformed config**: If `scorer_config` has wrong types (e.g., `ignore_case: "yes"` instead of `True`), the scorer should fail gracefully. Recommendation: don't add type validation in scorers — that's the suite loader's job (P2.3 `validate_suite`). Scorers assume well-formed config.
- **Unknown config keys**: Ignore silently. Don't raise on unknown keys — forward compatibility.
- **Empty `scorer_config`**: Works fine — all defaults apply.

**This is clean and simple.** No changes needed to the `TestTask` schema. The `scorer_config` dict is the right abstraction — each scorer owns its config keys.

### 8. Per-Scorer Design Notes

#### `exact_match`
- Normalize both `response` and `str(task.expected)` via `normalize_response()`
- Apply `ignore_case` (`.lower()` both) and `ignore_punctuation` (strip `string.punctuation`)
- Return `1.0` or `0.0` (float — no need for Score)
- **Edge case**: `task.expected` is `Any` — must `str()` it before comparison

#### `numeric_match`
- Strip non-numeric except `.` and `-`
- Extract first number via `r'-?[\d.]+'`
- Compare with `tolerance` config: `abs(float(extracted) - float(task.expected)) <= tolerance`
- Return `1.0` or `0.0`
- **Edge case**: no number found → `0.0` (extraction failure)
- **Edge case**: `task.expected` is not numeric → `str()` it, extract number from it too
- **P2.14 dual-filter**: Consider now, implement later. The `numeric_match` signature should already return `float | Score` so dual-filter can return `Score` with `sub_scores` without breaking the interface. For now, return `float`.

#### `regex_extract`
- `pattern` from `scorer_config` (required — if missing, return `0.0`)
- `group` from `scorer_config` (default: 1)
- `re.search(pattern, response)` — extract `group(group_num)`
- Compare extracted to `str(task.expected)`
- Return `1.0` or `0.0`
- **Edge case**: pattern doesn't match → `0.0`
- **Edge case**: invalid regex → catch `re.error`, return `0.0`

#### `contains`
- Check if `str(task.expected)` appears in `response`
- `ignore_case` config: `.lower()` both
- Return `1.0` or `0.0`
- **Edge case**: empty expected → `0.0` (don't match empty string in everything)

#### `json_valid`
- Strip code fences: `re.sub(r'^```(?:json)?\s*\n?', '', response)` and trailing ` ``` `
- `json.loads()` — return `0.0` on `JSONDecodeError`
- If `required_keys` config present: check each key exists in parsed dict
- Return `1.0` or `0.0`
- **Edge case**: empty response → `0.0`
- **Edge case**: valid JSON but missing required keys → `0.0`
- **Edge case**: `required_keys` not in config → just check JSON validity

#### `code_execution`
- Extract code from fences (```python, ``` or raw)
- Exec in sandbox (see section 4 above)
- Run `test_cases` from config: `score = passed / total`
- Return `Score(value, sub_scores={f"case_{i}": 0.0|1.0, ...}, explanation)`
- **Edge case**: no code found → `0.0`
- **Edge case**: no test_cases → `0.0` (can't score without tests)
- **Edge case**: exec error → `0.0` for that case, continue other cases

## Findings

### Strengths
- The `float | Score` return type is well-designed — simple scorers stay simple, complex scorers have full metadata
- The `Score` dataclass already has the right fields (`value`, `extracted`, `sub_scores`, `explanation`)
- `scorer_config` on `TestTask` is a clean config injection mechanism
- The 6-stage MCQ fallback has a logical specific-to-general progression

### Issues Found

| # | Issue | Severity | Recommendation |
|---|-------|----------|----------------|
| 1 | `runner.py` unpacks `score, extracted = scorer(...)` — breaks with new return type | **Critical** | Add `normalize_score_result()` helper, update `run_single_test` |
| 2 | `test_scorers.py` unpacks `score, extracted = mcq_scorer(...)` — all tests break | **High** | Rewrite tests to handle `float` return for simple scorers |
| 3 | `code_execution` sandbox via `exec` is not a true sandbox — attribute traversal escapes | **Medium** | Document as known limitation, acceptable for eval framework |
| 4 | `signal.alarm()` timeout is Unix-only | **Low** | Document, acceptable for now, note `multiprocessing` as future hardening |
| 5 | Stage 4 regex ambiguity: TODO says `^([ABCD])` but description says "paren pattern" | **Low** | Use `^([ABCD])\)` to match the existing behavior |
| 6 | `numeric_match` with `task.expected` as `Any` type — must handle non-string expected values | **Low** | `str()` the expected, then extract number from it |
| 7 | `json_valid` required_keys check — what if parsed JSON is a list, not a dict? | **Low** | Check `isinstance(parsed, dict)` before key lookup, return `0.0` if not dict |

### Compliance Check
- ✅ Scorer signatures follow the `float | Score` union type as specified
- ✅ `normalize_response` follows simple-evals implementation exactly
- ✅ All scorers handle edge cases (empty response, missing config, malformed input)
- ✅ `SCORERS` dict registers all new scorers
- ✅ `code_execution` returns `Score` with `sub_scores`
- ✅ Simple scorers return `float` (1.0/0.0) — no unnecessary `Score` wrapper

## Recommendations

### Implementation Order

1. **Add type aliases and `normalize_score_result` helper** — foundation for everything else
2. **Add `normalize_response`** — pure utility, no dependencies, test first
3. **Update `mcq_scorer`** to 6-stage fallback — modify existing code, update existing tests
4. **Add simple scorers** in order: `exact_match`, `numeric_match`, `regex_extract`, `contains`, `json_valid`
5. **Add `code_execution`** — most complex, do last
6. **Update `runner.py`** — single change to use `normalize_score_result`
7. **Update `test_scorers.py`** — rewrite for new return types
8. **Update `test_runner.py`** if needed (should not need changes if runner handles conversion)

### Clean Implementation Principles

1. **Don't wrap simple scorers in `Score`** — `return 1.0` is clearer than `return Score(value=1.0)`
2. **Don't validate `scorer_config` types in scorers** — that's the loader's job (P2.3)
3. **Don't catch broad `Exception` in scorers** — catch specific exceptions (`re.error`, `json.JSONDecodeError`, `ValueError`, `TypeError`)
4. **Don't add `normalize_response` to scorers that don't need it** — `contains` and `json_valid` operate on raw response; only `exact_match` and `mcq_scorer` benefit from normalization
5. **Keep `normalize_response` as a pure function** — no side effects, no dependencies, testable in isolation

### Type Alias Design

```python
from collections.abc import Callable
from yoker_test.schema import Score, TestTask

ScorerResult = float | Score
ScorerFunc = Callable[[TestTask, str], ScorerResult]
```

This keeps signatures readable throughout:
- Function defs: `def exact_match(task: TestTask, response: str) -> ScorerResult:`
- Registry: `SCORERS: dict[str, ScorerFunc] = {...}`
- Helper: `def normalize_score_result(result: ScorerResult) -> tuple[float, str | None, dict[str, float] | None]:`

## Action Items

- [ ] Implement `normalize_response` with simple-evals ordering (copy exact chain, add docstring)
- [ ] Implement `normalize_score_result` helper for runner compatibility
- [ ] Update `mcq_scorer` to 6-stage fallback (stage 3 = first line only, stage 5 = full response)
- [ ] Implement `exact_match` with `ignore_case` and `ignore_punctuation` config
- [ ] Implement `numeric_match` with `tolerance` config (return `float` for now, P2.14 will extend to `Score`)
- [ ] Implement `regex_extract` with `pattern` (required) and `group` (default: 1) config
- [ ] Implement `contains` with `ignore_case` config
- [ ] Implement `json_valid` with `required_keys` optional config
- [ ] Implement `code_execution` with sandboxed `exec`, `timeout` and `test_cases` config
- [ ] Update `SCORERS` dict with all 7 scorers
- [ ] Update `runner.py` `run_single_test` to use `normalize_score_result`
- [ ] Update `test_scorers.py` — rewrite all MCQ tests for 6-stage fallback and `float` return
- [ ] Add tests for all new scorers covering: correct, incorrect, empty response, missing config, malformed input
- [ ] Add tests for `normalize_response` with markdown/LaTeX patterns
- [ ] Add tests for `normalize_score_result` helper
- [ ] Verify `test_runner.py` still passes (should not need changes)

## Conclusion

**Status**: Approved for implementation

The design is sound. The `float | Score` return type is the right abstraction — simple scorers stay simple, complex scorers have rich metadata. The key risk is the `runner.py` change, which is contained and straightforward via the `normalize_score_result` helper. The `code_execution` sandbox is not a true security sandbox but is acceptable for a model eval framework where prompts are controlled.

The `normalize_response` utility must follow the simple-evals ordering exactly — the chain ordering is load-bearing and should not be modified. The 6-stage MCQ fallback correctly progresses from specific (first line) to general (full response).

**Next step**: Implement the scorers following the implementation order above, with tests.