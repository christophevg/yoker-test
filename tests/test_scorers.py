"""Tests for yoker_test.scorers."""

import pytest

from yoker_test.schema import Score, TestTask
from yoker_test.scorers import (
  SCORERS,
  code_execution,
  contains,
  exact_match,
  json_valid,
  mcq_scorer,
  normalize_response,
  normalize_score_result,
  numeric_match,
  regex_extract,
)


def make_task(
  expected: str = "C",
  scorer: str | object = "mcq",
  scorer_config: dict | None = None,
) -> TestTask:
  """Create a minimal test task for testing."""
  if scorer_config is None:
    scorer_config = {}
  return TestTask(
    id="K1",
    category="knowledge",
    prompt="?",
    expected=expected,
    scorer=scorer,
    scorer_config=scorer_config,
  )


class TestMcqScorerExactLetter:
  """Stage 1: Response is exactly one of A/B/C/D."""

  def test_correct_exact_letter(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "C") == 1.0

  def test_incorrect_exact_letter(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "B") == 0.0

  def test_exact_letter_strips_whitespace(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "  A  \n") == 1.0

  @pytest.mark.parametrize("letter", ["A", "B", "C", "D"])
  def test_all_letters_recognized(self, letter):
    task = make_task(expected=letter)
    assert mcq_scorer(task, letter) == 1.0


class TestMcqScorerAnswerPattern:
  """Stage 2: "Answer: B" pattern."""

  def test_correct_answer_pattern(self):
    task = make_task(expected="B")
    assert mcq_scorer(task, "Answer: B") == 1.0

  def test_incorrect_answer_pattern(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "Answer: B") == 0.0

  def test_answer_pattern_case_insensitive(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "answer: c") == 1.0

  def test_answer_pattern_with_dollar_signs(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "Answer: $A$") == 1.0

  def test_answer_pattern_with_extra_text(self):
    task = make_task(expected="D")
    assert mcq_scorer(task, "I think the answer is\nAnswer: D\nbecause gold") == 1.0

  def test_answer_pattern_with_tabs(self):
    task = make_task(expected="B")
    assert mcq_scorer(task, "Answer:\tB") == 1.0


class TestMcqScorerFirstLineLetter:
  """Stage 3: First standalone A/B/C/D on first line only."""

  def test_correct_first_line_letter(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "A is the answer\nB is wrong") == 1.0

  def test_incorrect_first_line_letter(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "A is the answer\nB is wrong") == 0.0

  def test_letter_on_second_line_not_matched_stage3(self):
    """First line has no letter, so stage 3 fails; stage 5 catches it."""
    task = make_task(expected="B")
    result = mcq_scorer(task, "Some text\nB is the answer")
    assert result == 1.0

  def test_standalone_letter_picks_first_on_first_line(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "A and then B") == 1.0

  def test_letter_not_in_word(self):
    """Letters inside words should not match on first line."""
    task = make_task(expected="A")
    assert mcq_scorer(task, "The Apple is red") == 0.0


class TestMcqScorerParenPattern:
  """Stage 4: "B) Paris" pattern (letter at start followed by parenthesis)."""

  def test_correct_paren_pattern(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "C) Paris") == 1.0

  def test_incorrect_paren_pattern(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "C) Paris") == 0.0

  def test_paren_pattern_with_extra_text(self):
    task = make_task(expected="B")
    assert mcq_scorer(task, "B) London is the capital") == 1.0


class TestMcqScorerFullResponseLetter:
  """Stage 5: First standalone A/B/C/D on full response."""

  def test_letter_only_on_second_line(self):
    task = make_task(expected="B")
    assert mcq_scorer(task, "No letter here\nB is correct") == 1.0

  def test_incorrect_letter_on_second_line(self):
    task = make_task(expected="C")
    assert mcq_scorer(task, "No letter here\nB is correct") == 0.0


class TestMcqScorerNoMatch:
  """Stage 6: No letter found in response."""

  def test_no_letter_returns_zero(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "I don't know the answer") == 0.0

  def test_empty_response(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "") == 0.0

  def test_whitespace_only_response(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "   \n\t  ") == 0.0

  def test_letter_outside_abcd_range(self):
    task = make_task(expected="A")
    assert mcq_scorer(task, "E") == 0.0


class TestNormalizeResponse:
  """Tests for normalize_response utility."""

  def test_strips_bold_markdown(self):
    assert normalize_response("**bold**") == "bold"

  def test_strips_latex_boxed(self):
    assert normalize_response("$\\boxed{A}$") == "A"

  def test_strips_dollar_signs(self):
    assert normalize_response("$A$") == "A"

  def test_strips_mathrm(self):
    # \mathrm{ removed, { removed, but trailing } stays (no $ to match }$)
    assert normalize_response("\\mathrm{A}") == "A}"

  def test_strips_text_command(self):
    assert normalize_response("$\\text{A}$") == "A"

  def test_strips_braces(self):
    # { is removed but } is not — matches simple-evals behavior
    assert normalize_response("{A}") == "A}"

  def test_strips_mathbf(self):
    # \mathbf{ removed, { removed, trailing } stays
    assert normalize_response("\\mathbf{A}") == "A}"

  def test_plain_text_unchanged(self):
    assert normalize_response("hello") == "hello"

  def test_empty_string(self):
    assert normalize_response("") == ""

  def test_ordering_boxed_before_bare_dollar(self):
    """$-prefixed patterns must be removed before bare $."""
    result = normalize_response("$\\boxed{B}$")
    assert result == "B"


class TestNormalizeScoreResult:
  """Tests for normalize_score_result helper."""

  def test_float_input(self):
    value, extracted, sub_scores = normalize_score_result(1.0)
    assert value == 1.0
    assert extracted is None
    assert sub_scores is None

  def test_zero_float_input(self):
    value, extracted, sub_scores = normalize_score_result(0.0)
    assert value == 0.0
    assert extracted is None
    assert sub_scores is None

  def test_score_object(self):
    score = Score(value=0.5, extracted="A", sub_scores={"case_0": 1.0})
    value, extracted, sub_scores = normalize_score_result(score)
    assert value == 0.5
    assert extracted == "A"
    assert sub_scores == {"case_0": 1.0}

  def test_score_object_with_none_fields(self):
    score = Score(value=1.0)
    value, extracted, sub_scores = normalize_score_result(score)
    assert value == 1.0
    assert extracted is None
    assert sub_scores is None


class TestExactMatch:
  """Tests for exact_match scorer."""

  def test_correct_match(self):
    task = make_task(expected="hello", scorer="exact_match")
    assert exact_match(task, "hello") == 1.0

  def test_incorrect_match(self):
    task = make_task(expected="hello", scorer="exact_match")
    assert exact_match(task, "world") == 0.0

  def test_ignore_case(self):
    task = make_task(expected="Hello", scorer="exact_match", scorer_config={"ignore_case": True})
    assert exact_match(task, "hello") == 1.0

  def test_ignore_case_false(self):
    task = make_task(expected="Hello", scorer="exact_match", scorer_config={"ignore_case": False})
    assert exact_match(task, "hello") == 0.0

  def test_ignore_punctuation(self):
    task = make_task(
      expected="hello", scorer="exact_match", scorer_config={"ignore_punctuation": True}
    )
    assert exact_match(task, "hello!") == 1.0

  def test_ignore_punctuation_false(self):
    task = make_task(
      expected="hello", scorer="exact_match", scorer_config={"ignore_punctuation": False}
    )
    assert exact_match(task, "hello!") == 0.0

  def test_latex_normalized(self):
    task = make_task(expected="A", scorer="exact_match")
    assert exact_match(task, "$\\boxed{A}$") == 1.0

  def test_empty_response(self):
    task = make_task(expected="hello", scorer="exact_match")
    assert exact_match(task, "") == 0.0

  def test_integer_expected(self):
    task = make_task(expected=42, scorer="exact_match")
    assert exact_match(task, "42") == 1.0


class TestNumericMatch:
  """Tests for numeric_match scorer."""

  def test_correct_integer(self):
    task = make_task(expected=42, scorer="numeric_match")
    assert numeric_match(task, "The answer is 42") == 1.0

  def test_incorrect_integer(self):
    task = make_task(expected=42, scorer="numeric_match")
    assert numeric_match(task, "The answer is 37") == 0.0

  def test_correct_float(self):
    task = make_task(expected=3.14, scorer="numeric_match")
    assert numeric_match(task, "3.14") == 1.0

  def test_with_tolerance(self):
    task = make_task(expected=10.0, scorer="numeric_match", scorer_config={"tolerance": 0.5})
    assert numeric_match(task, "10.3") == 1.0

  def test_outside_tolerance(self):
    task = make_task(expected=10.0, scorer="numeric_match", scorer_config={"tolerance": 0.5})
    assert numeric_match(task, "11.0") == 0.0

  def test_negative_number(self):
    task = make_task(expected=-5, scorer="numeric_match")
    assert numeric_match(task, "-5") == 1.0

  def test_no_number_in_response(self):
    task = make_task(expected=42, scorer="numeric_match")
    assert numeric_match(task, "no numbers here") == 0.0

  def test_number_embedded_in_text(self):
    task = make_task(expected=100, scorer="numeric_match")
    assert numeric_match(task, "The result is 100 units") == 1.0

  def test_expected_as_string_number(self):
    task = make_task(expected="42", scorer="numeric_match")
    assert numeric_match(task, "42") == 1.0

  def test_expected_non_numeric(self):
    task = make_task(expected="abc", scorer="numeric_match")
    assert numeric_match(task, "42") == 0.0


class TestRegexExtract:
  """Tests for regex_extract scorer."""

  def test_correct_extraction(self):
    task = make_task(
      expected="42",
      scorer="regex_extract",
      scorer_config={"pattern": r"Answer:\s*(\d+)"},
    )
    assert regex_extract(task, "Answer: 42") == 1.0

  def test_incorrect_extraction(self):
    task = make_task(
      expected="42",
      scorer="regex_extract",
      scorer_config={"pattern": r"Answer:\s*(\d+)"},
    )
    assert regex_extract(task, "Answer: 37") == 0.0

  def test_no_match(self):
    task = make_task(
      expected="42",
      scorer="regex_extract",
      scorer_config={"pattern": r"Answer:\s*(\d+)"},
    )
    assert regex_extract(task, "No pattern here") == 0.0

  def test_missing_pattern(self):
    task = make_task(expected="42", scorer="regex_extract", scorer_config={})
    assert regex_extract(task, "42") == 0.0

  def test_invalid_regex(self):
    task = make_task(
      expected="42",
      scorer="regex_extract",
      scorer_config={"pattern": r"[invalid("},
    )
    assert regex_extract(task, "42") == 0.0

  def test_group_specified(self):
    task = make_task(
      expected="Paris",
      scorer="regex_extract",
      scorer_config={"pattern": r"(\w+)", "group": 1},
    )
    assert regex_extract(task, "Paris") == 1.0

  def test_group_out_of_range(self):
    task = make_task(
      expected="42",
      scorer="regex_extract",
      scorer_config={"pattern": r"(\d+)", "group": 5},
    )
    assert regex_extract(task, "42") == 0.0


class TestContains:
  """Tests for contains scorer."""

  def test_correct_contains(self):
    task = make_task(expected="Paris", scorer="contains")
    assert contains(task, "The capital is Paris") == 1.0

  def test_incorrect_contains(self):
    task = make_task(expected="Paris", scorer="contains")
    assert contains(task, "The capital is London") == 0.0

  def test_ignore_case(self):
    task = make_task(expected="paris", scorer="contains", scorer_config={"ignore_case": True})
    assert contains(task, "The capital is Paris") == 1.0

  def test_ignore_case_false(self):
    task = make_task(expected="paris", scorer="contains", scorer_config={"ignore_case": False})
    assert contains(task, "The capital is Paris") == 0.0

  def test_empty_expected(self):
    task = make_task(expected="", scorer="contains")
    assert contains(task, "anything") == 0.0

  def test_empty_response(self):
    task = make_task(expected="Paris", scorer="contains")
    assert contains(task, "") == 0.0

  def test_partial_match(self):
    task = make_task(expected="aris", scorer="contains")
    assert contains(task, "Paris") == 1.0


class TestJsonValid:
  """Tests for json_valid scorer."""

  def test_valid_json(self):
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, '{"key": "value"}') == 1.0

  def test_invalid_json(self):
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, "not json") == 0.0

  def test_empty_response(self):
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, "") == 0.0

  def test_json_with_code_fence(self):
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, '```json\n{"key": "value"}\n```') == 1.0

  def test_json_with_plain_code_fence(self):
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, '```\n{"key": "value"}\n```') == 1.0

  def test_required_keys_present(self):
    task = make_task(
      expected="",
      scorer="json_valid",
      scorer_config={"required_keys": ["name", "age"]},
    )
    assert json_valid(task, '{"name": "Alice", "age": 30}') == 1.0

  def test_required_keys_missing(self):
    task = make_task(
      expected="",
      scorer="json_valid",
      scorer_config={"required_keys": ["name", "age"]},
    )
    assert json_valid(task, '{"name": "Alice"}') == 0.0

  def test_required_keys_empty(self):
    task = make_task(
      expected="",
      scorer="json_valid",
      scorer_config={"required_keys": []},
    )
    assert json_valid(task, '{"name": "Alice"}') == 1.0

  def test_json_list_with_required_keys(self):
    """JSON list (not dict) with required_keys should fail."""
    task = make_task(
      expected="",
      scorer="json_valid",
      scorer_config={"required_keys": ["name"]},
    )
    assert json_valid(task, '["a", "b"]') == 0.0

  def test_json_list_without_required_keys(self):
    """JSON list without required_keys config should pass."""
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, '["a", "b"]') == 1.0

  def test_no_required_keys_config(self):
    task = make_task(expected="", scorer="json_valid")
    assert json_valid(task, '{"key": "value"}') == 1.0


class TestCodeExecution:
  """Tests for code_execution scorer."""

  def test_correct_solution(self):
    code = "def solution(a, b):\n  return a + b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
          {"func": "solution", "args": [5, 5], "expected": 10},
        ]
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 1.0
    assert result.sub_scores == {"case_0": 1.0, "case_1": 1.0}

  def test_partial_correct(self):
    code = "def solution(a, b):\n  return a + b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
          {"func": "solution", "args": [5, 5], "expected": 11},
        ]
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 0.5
    assert result.sub_scores == {"case_0": 1.0, "case_1": 0.0}

  def test_no_code_found(self):
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={"test_cases": [{"func": "solution", "args": [], "expected": 1}]},
    )
    assert code_execution(task, "") == 0.0

  def test_no_test_cases(self):
    task = make_task(expected="", scorer="code_execution", scorer_config={})
    code = "def solution():\n  return 1"
    assert code_execution(task, code) == 0.0

  def test_exec_error(self):
    code = "def solution(a, b):\n  return a / b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 0], "expected": None},
        ]
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 0.0
    assert result.sub_scores == {"case_0": 0.0}

  def test_func_not_found(self):
    code = "def wrong_name(a, b):\n  return a + b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
        ]
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 0.0
    assert result.sub_scores == {"case_0": 0.0}

  def test_plain_code_fence(self):
    code = "def solution(a, b):\n  return a + b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
        ]
      },
    )
    result = code_execution(task, f"```\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 1.0

  def test_raw_code_no_fence(self):
    code = "def solution(a, b):\n  return a + b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
        ]
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 1.0

  def test_explanation_in_result(self):
    code = "def solution(a, b):\n  return a + b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
        ]
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.explanation == "1/1 cases passed"

  def test_all_cases_wrong(self):
    code = "def solution(a, b):\n  return a - b"
    task = make_task(
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
          {"func": "solution", "args": [5, 5], "expected": 10},
        ]
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 0.0
    assert result.sub_scores == {"case_0": 0.0, "case_1": 0.0}


class TestScorersRegistry:
  """Tests for the SCORERS registry."""

  @pytest.mark.parametrize(
    "name,func",
    [
      ("mcq", mcq_scorer),
      ("exact_match", exact_match),
      ("numeric_match", numeric_match),
      ("regex_extract", regex_extract),
      ("contains", contains),
      ("json_valid", json_valid),
      ("code_execution", code_execution),
    ],
  )
  def test_scorer_registered(self, name, func):
    assert name in SCORERS
    assert SCORERS[name] is func

  def test_mcq_scorer_via_registry(self):
    task = make_task(expected="C")
    assert SCORERS["mcq"](task, "C") == 1.0

  def test_all_seven_scorers(self):
    assert len(SCORERS) == 7
