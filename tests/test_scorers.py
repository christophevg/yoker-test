"""Tests for yoker_test.scorers."""

import pytest

from yoker_test.schema import TestTask
from yoker_test.scorers import SCORERS, mcq_scorer


def make_task(expected: str = "C") -> TestTask:
  """Create a minimal MCQ task for testing."""
  return TestTask(id="K1", category="knowledge", prompt="?", expected=expected, scorer="mcq")


class TestMcqScorerExactLetter:
  """Path 1: Response is exactly one of A/B/C/D."""

  def test_correct_exact_letter(self):
    task = make_task(expected="C")
    score, extracted = mcq_scorer(task, "C")
    assert score == 1.0
    assert extracted == "C"

  def test_incorrect_exact_letter(self):
    task = make_task(expected="C")
    score, extracted = mcq_scorer(task, "B")
    assert score == 0.0
    assert extracted == "B"

  def test_exact_letter_strips_whitespace(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "  A  \n")
    assert score == 1.0
    assert extracted == "A"

  @pytest.mark.parametrize("letter", ["A", "B", "C", "D"])
  def test_all_letters_recognized(self, letter):
    task = make_task(expected=letter)
    score, extracted = mcq_scorer(task, letter)
    assert score == 1.0
    assert extracted == letter


class TestMcqScorerAnswerPattern:
  """Path 2: "Answer: B" pattern."""

  def test_correct_answer_pattern(self):
    task = make_task(expected="B")
    score, extracted = mcq_scorer(task, "Answer: B")
    assert score == 1.0
    assert extracted == "B"

  def test_incorrect_answer_pattern(self):
    task = make_task(expected="C")
    score, extracted = mcq_scorer(task, "Answer: B")
    assert score == 0.0
    assert extracted == "B"

  def test_answer_pattern_case_insensitive(self):
    task = make_task(expected="C")
    score, extracted = mcq_scorer(task, "answer: c")
    assert score == 1.0
    assert extracted == "C"

  def test_answer_pattern_with_dollar_signs(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "Answer: $A$")
    assert score == 1.0
    assert extracted == "A"

  def test_answer_pattern_with_extra_text(self):
    task = make_task(expected="D")
    score, extracted = mcq_scorer(task, "I think the answer is\nAnswer: D\nbecause gold")
    assert score == 1.0
    assert extracted == "D"

  def test_answer_pattern_with_tabs(self):
    task = make_task(expected="B")
    score, extracted = mcq_scorer(task, "Answer:\tB")
    assert score == 1.0
    assert extracted == "B"


class TestMcqScorerStandaloneLetter:
  """Path 3: First standalone A/B/C/D in text."""

  def test_correct_standalone_letter(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "The answer is A because of reasons")
    assert score == 1.0
    assert extracted == "A"

  def test_incorrect_standalone_letter(self):
    task = make_task(expected="C")
    score, extracted = mcq_scorer(task, "The answer is A because of reasons")
    assert score == 0.0
    assert extracted == "A"

  def test_standalone_letter_picks_first(self):
    """When multiple letters appear, the first standalone one is used."""
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "A and then B and then C")
    assert score == 1.0
    assert extracted == "A"

  def test_standalone_letter_not_in_word(self):
    """Letters inside words should not match."""
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "The Apple is red")
    assert score == 0.0
    assert extracted is None


class TestMcqScorerParenPattern:
  """Path 4: "B) Paris" pattern (letter at start followed by parenthesis)."""

  def test_correct_paren_pattern(self):
    task = make_task(expected="C")
    score, extracted = mcq_scorer(task, "C) Paris")
    assert score == 1.0
    assert extracted == "C"

  def test_incorrect_paren_pattern(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "C) Paris")
    assert score == 0.0
    assert extracted == "C"

  def test_paren_pattern_with_extra_text(self):
    task = make_task(expected="B")
    score, extracted = mcq_scorer(task, "B) London is the capital")
    assert score == 1.0
    assert extracted == "B"


class TestMcqScorerNoMatch:
  """No letter found in response."""

  def test_no_letter_returns_zero(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "I don't know the answer")
    assert score == 0.0
    assert extracted is None

  def test_empty_response(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "")
    assert score == 0.0
    assert extracted is None

  def test_whitespace_only_response(self):
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "   \n\t  ")
    assert score == 0.0
    assert extracted is None

  def test_letter_outside_abcd_range(self):
    """Letters E-Z should not match."""
    task = make_task(expected="A")
    score, extracted = mcq_scorer(task, "E")
    assert score == 0.0
    assert extracted is None


class TestScorersRegistry:
  """Tests for the SCORERS registry."""

  def test_mcq_scorer_registered(self):
    assert "mcq" in SCORERS
    assert SCORERS["mcq"] is mcq_scorer

  def test_scorer_callable_via_registry(self):
    task = make_task(expected="C")
    scorer = SCORERS["mcq"]
    score, extracted = scorer(task, "C")
    assert score == 1.0
    assert extracted == "C"
