"""Scorers for yoker-test: score model responses against expected answers."""

import json
import os
import re
import string
import subprocess
import sys
import tempfile
from collections.abc import Callable

from yoker_test.schema import Score, TestTask

ScorerResult = float | Score
ScorerFunc = Callable[[TestTask, str], ScorerResult]


def normalize_score_result(
  result: ScorerResult,
) -> tuple[float, str | None, dict[str, float] | None]:
  """Convert float | Score to (value, extracted, sub_scores)."""
  if isinstance(result, Score):
    return result.value, result.extracted, result.sub_scores
  return result, None, None


def normalize_response(response: str) -> str:
  """Strip markdown/LaTeX formatting from model responses.

  Order matters: $-prefixed patterns must be removed before bare $,
  {-prefixed patterns before bare {. See simple-evals common.py.
  """
  return (
    response.replace("**", "")
    .replace("$\\boxed{", "")
    .replace("}$", "")
    .replace("\\$", "")
    .replace("$\\text{", "")
    .replace("$", "")
    .replace("\\mathrm{", "")
    .replace("\\{", "")
    .replace("\\text", "")
    .replace("\\(", "")
    .replace("\\mathbf{", "")
    .replace("{", "")
    .replace("\\boxed", "")
  )


def mcq_scorer(task: TestTask, response: str) -> ScorerResult:
  """Extract A-D from response via 6-stage fallback, compare to expected."""
  text = response.strip()

  # 1. Response is exactly one of A/B/C/D
  if text in ("A", "B", "C", "D"):
    return 1.0 if text == task.expected else 0.0

  # 2. "Answer: B" pattern (case-insensitive)
  m = re.search(r"(?i)Answer[ \t]*:[ \t]*\$?([A-D])\$?", text)
  if m:
    letter = m.group(1).upper()
    return 1.0 if letter == task.expected else 0.0

  # 3. First standalone A/B/C/D on first line only
  first_line = text.split("\n")[0]
  m = re.search(r"\b([ABCD])\b", first_line)
  if m:
    letter = m.group(1).upper()
    return 1.0 if letter == task.expected else 0.0

  # 4. "B) Paris" pattern (letter at start followed by parenthesis)
  m = re.match(r"^([ABCD])\)", text)
  if m:
    letter = m.group(1).upper()
    return 1.0 if letter == task.expected else 0.0

  # 5. First standalone A/B/C/D on full response
  m = re.search(r"\b([ABCD])\b", text)
  if m:
    letter = m.group(1).upper()
    return 1.0 if letter == task.expected else 0.0

  # 6. No match
  return 0.0


def exact_match(task: TestTask, response: str) -> ScorerResult:
  """Normalize both sides and compare for exact equality."""
  expected = normalize_response(str(task.expected))
  actual = normalize_response(response)

  if task.scorer_config.get("ignore_case", False):
    expected = expected.lower()
    actual = actual.lower()

  if task.scorer_config.get("ignore_punctuation", False):
    expected = expected.translate(str.maketrans("", "", string.punctuation))
    actual = actual.translate(str.maketrans("", "", string.punctuation))

  return 1.0 if actual == expected else 0.0


def numeric_match(task: TestTask, response: str) -> ScorerResult:
  """Extract first number from response, compare with tolerance."""
  tolerance = task.scorer_config.get("tolerance", 0.0)

  resp_match = re.search(r"-?[\d.]+", response)
  if not resp_match:
    return 0.0
  resp_num = float(resp_match.group())

  expected_str = str(task.expected)
  exp_match = re.search(r"-?[\d.]+", expected_str)
  if not exp_match:
    return 0.0
  expected_num = float(exp_match.group())

  return 1.0 if abs(resp_num - expected_num) <= tolerance else 0.0


def regex_extract(task: TestTask, response: str) -> ScorerResult:
  """Extract a value via regex pattern, compare to expected."""
  pattern = task.scorer_config.get("pattern")
  if not pattern:
    return 0.0

  group = task.scorer_config.get("group", 1)

  try:
    m = re.search(pattern, response)
  except re.error:
    return 0.0

  if not m:
    return 0.0

  try:
    extracted = m.group(group)
  except IndexError:
    return 0.0

  return 1.0 if extracted == str(task.expected) else 0.0


def contains(task: TestTask, response: str) -> ScorerResult:
  """Check if expected string appears in response."""
  expected = str(task.expected)
  if not expected:
    return 0.0

  if task.scorer_config.get("ignore_case", False):
    return 1.0 if expected.lower() in response.lower() else 0.0

  return 1.0 if expected in response else 0.0


def json_valid(task: TestTask, response: str) -> ScorerResult:
  """Validate JSON response, optionally checking required keys."""
  if not response.strip():
    return 0.0

  # Strip code fences
  stripped = response.strip()
  if stripped.startswith("```"):
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", stripped)
    stripped = re.sub(r"\n?```\s*$", "", stripped)

  try:
    parsed = json.loads(stripped)
  except json.JSONDecodeError:
    return 0.0

  required_keys = task.scorer_config.get("required_keys")
  if required_keys:
    if not isinstance(parsed, dict):
      return 0.0
    if not all(key in parsed for key in required_keys):
      return 0.0

  return 1.0


def _extract_code(response: str) -> str | None:
  """Extract Python code from markdown fences or raw response."""
  m = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
  if m:
    return m.group(1).strip()
  m = re.search(r"```\s*\n(.*?)```", response, re.DOTALL)
  if m:
    return m.group(1).strip()
  stripped = response.strip()
  if stripped:
    return stripped
  return None


def code_execution(task: TestTask, response: str) -> ScorerResult:
  """Execute extracted code against test cases in a subprocess.

  Writes the LLM-generated code and test-case runner to a temp file,
  executes it via subprocess with timeout, and parses JSON results from
  stdout. OS-level isolation protects the host process.
  """
  code = _extract_code(response)
  if not code:
    return 0.0

  test_cases = task.scorer_config.get("test_cases", [])
  if not test_cases:
    return 0.0

  timeout = task.scorer_config.get("timeout", 5)

  # Build runner script: define code into a namespace, run each test case, print JSON
  runner_lines = [
    "import json, sys",
    "results = {}",
    "_ns = {}",
    "try:",
    f"    exec({code!r}, _ns)",
    "except Exception as e:",
    f"    for i in range({len(test_cases)}):",
    "        results[f'case_{i}'] = {'score': 0.0, 'error': str(e)}",
    "    print(json.dumps(results))",
    "    sys.exit(0)",
  ]
  for i, tc in enumerate(test_cases):
    func_name = tc.get("func", "solution")
    args = tc.get("args", [])
    expected = tc.get("expected")
    runner_lines.extend(
      [
        "try:",
        f"    _func = _ns.get({func_name!r})",
        "    if _func is None or not callable(_func):",
        f"        results['case_{i}'] = {{'score': 0.0}}",
        "    else:",
        f"        _result = _func(*{args!r})",
        f"        results['case_{i}'] = {{'score': 1.0 if _result == {expected!r} else 0.0}}",
        "except Exception as e:",
        f"    results['case_{i}'] = {{'score': 0.0, 'error': str(e)}}",
      ]
    )
  runner_lines.append("print(json.dumps(results))")
  runner = "\n".join(runner_lines) + "\n"

  with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
    f.write(runner)
    tmp_path = f.name

  try:
    result = subprocess.run(
      [sys.executable, tmp_path],
      capture_output=True,
      timeout=timeout,
      text=True,
    )
    try:
      parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
      parsed = {f"case_{i}": 0.0 for i in range(len(test_cases))}
  except subprocess.TimeoutExpired:
    parsed = {f"case_{i}": 0.0 for i in range(len(test_cases))}
  finally:
    os.unlink(tmp_path)

  results: dict[str, float] = {}
  passed = 0
  for i in range(len(test_cases)):
    key = f"case_{i}"
    case_result = parsed.get(key, 0.0)
    if isinstance(case_result, dict):
      score_val = case_result.get("score", 0.0)
    else:
      score_val = case_result
    results[key] = score_val
    if score_val == 1.0:
      passed += 1

  total = len(test_cases)
  value = passed / total if total > 0 else 0.0
  return Score(
    value=value,
    sub_scores=results,
    explanation=f"{passed}/{total} cases passed",
  )


SCORERS: dict[str, ScorerFunc] = {
  "mcq": mcq_scorer,
  "exact_match": exact_match,
  "numeric_match": numeric_match,
  "regex_extract": regex_extract,
  "contains": contains,
  "json_valid": json_valid,
  "code_execution": code_execution,
}
