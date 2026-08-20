"""Tests for yoker_test.report."""

from yoker_test.report import compute_composite, print_report
from yoker_test.schema import TestResult, TestTask


def make_task(expected: str = "C") -> TestTask:
  return TestTask(id="K1", category="knowledge", prompt="?", expected=expected, scorer="mcq")


def make_result(score: float = 1.0, error: str | None = None) -> TestResult:
  return TestResult(
    task_id="K1",
    category="knowledge",
    score=score,
    response="C",
    extracted="C",
    tokens_in=100,
    tokens_out=50,
    latency_ms=500.0,
    thinking_chars=200,
    content_chars=100,
    error=error,
  )


class TestComputeCompositeFreeModel:
  """Free models (cost_delta=None or 0) → cost_score=1.0 → composite=quality."""

  def test_none_cost_delta(self):
    assert compute_composite(quality=0.8, cost_delta=None, n_tasks=10, n_correct=8) == 0.8

  def test_zero_cost_delta(self):
    assert compute_composite(quality=0.5, cost_delta=0.0, n_tasks=10, n_correct=5) == 0.5

  def test_negative_cost_delta(self):
    assert compute_composite(quality=0.9, cost_delta=-0.1, n_tasks=10, n_correct=9) == 0.9


class TestComputeCompositePaidModel:
  """Paid models: composite = quality × (1 / (1 + cost_per_correct × scale))."""

  def test_expensive_model_reduces_score(self):
    # cost_per_correct = 0.01 / 1 = 0.01, cost_score = 1/(1+0.01*1000) = 1/11 ≈ 0.091
    composite = compute_composite(quality=1.0, cost_delta=0.01, n_tasks=1, n_correct=1)
    assert abs(composite - 1.0 / 11.0) < 1e-9

  def test_cheap_model_keeps_score_high(self):
    # cost_per_correct = 0.0001 / 1 = 0.0001, cost_score = 1/(1+0.0001*1000) = 1/1.1
    composite = compute_composite(quality=1.0, cost_delta=0.0001, n_tasks=1, n_correct=1)
    assert abs(composite - 1.0 / 1.1) < 1e-9

  def test_quality_is_floor(self):
    """Wrong answers can't be cheap enough to score well."""
    composite = compute_composite(quality=0.0, cost_delta=0.0, n_tasks=10, n_correct=0)
    assert composite == 0.0

  def test_custom_scale(self):
    # With scale=100: cost_per_correct = 0.01/1 = 0.01, cost_score = 1/(1+0.01*100) = 1/2
    composite = compute_composite(quality=1.0, cost_delta=0.01, n_tasks=1, n_correct=1, scale=100.0)
    assert abs(composite - 0.5) < 1e-9


class TestComputeCompositeEdgeCases:
  """Edge cases for composite formula."""

  def test_zero_correct_with_cost(self):
    """n_correct < 1 → cost_score defaults to 1.0."""
    composite = compute_composite(quality=0.5, cost_delta=0.01, n_tasks=10, n_correct=0)
    assert composite == 0.5

  def test_fractional_correct_below_one(self):
    """n_correct < 1 → cost_score defaults to 1.0."""
    composite = compute_composite(quality=0.05, cost_delta=0.01, n_tasks=20, n_correct=1.0)
    # n_correct=1.0 is not < 1, so cost applies
    # cost_per_correct = 0.01/1 = 0.01, cost_score = 1/(1+10) = 1/11
    assert abs(composite - 0.05 / 11.0) < 1e-9


class TestPrintReport:
  """Tests for print_report output."""

  def test_prints_basic_report(self, capsys):
    task = make_task()
    result = make_result()
    print_report(task, result, None, None)
    output = capsys.readouterr().out
    assert "Score:" in output
    assert "Response:" in output
    assert "Extracted:" in output
    assert "Expected:" in output
    assert "Tokens in:" in output
    assert "Tokens out:" in output
    assert "Latency:" in output
    assert "Composite:" in output

  def test_prints_thinking_content_split(self, capsys):
    task = make_task()
    result = TestResult(
      task_id="K1",
      category="knowledge",
      score=1.0,
      response="C",
      extracted="C",
      tokens_in=100,
      tokens_out=50,
      latency_ms=500.0,
      thinking_chars=300,
      content_chars=100,
    )
    print_report(task, result, None, None)
    output = capsys.readouterr().out
    assert "75%" in output  # thinking is 75% of 400
    assert "25%" in output  # content is 25%

  def test_prints_zero_chars_without_percentage(self, capsys):
    task = make_task()
    result = make_result()
    result.thinking_chars = 0
    result.content_chars = 0
    print_report(task, result, None, None)
    output = capsys.readouterr().out
    assert "Thinking:   0 chars\n" in output
    assert "Content:    0 chars\n" in output

  def test_prints_usage_when_available(self, capsys):
    task = make_task()
    result = make_result()
    usage_before = {"session": 0.10, "weekly": 0.50}
    usage_after = {"session": 0.12, "weekly": 0.51}
    print_report(task, result, usage_before, usage_after)
    output = capsys.readouterr().out
    assert "Session:" in output
    assert "Weekly:" in output
    assert "10.0000%" in output
    assert "12.0000%" in output

  def test_omits_usage_when_none(self, capsys):
    task = make_task()
    result = make_result()
    print_report(task, result, None, None)
    output = capsys.readouterr().out
    assert "Session:" not in output
    assert "Weekly:" not in output

  def test_prints_error_when_present(self, capsys):
    task = make_task()
    result = make_result(error="Connection failed")
    print_report(task, result, None, None)
    output = capsys.readouterr().out
    assert "Error:" in output
    assert "Connection failed" in output

  def test_omits_error_when_none(self, capsys):
    task = make_task()
    result = make_result(error=None)
    print_report(task, result, None, None)
    output = capsys.readouterr().out
    assert "Error:" not in output

  def test_returns_composite_score(self, capsys):
    task = make_task()
    result = make_result(score=1.0)
    composite = print_report(task, result, None, None)
    assert composite == 1.0  # free model, perfect quality

  def test_returns_composite_with_cost(self, capsys):
    task = make_task()
    result = make_result(score=1.0)
    usage_before = {"session": 0.0, "weekly": 0.0}
    usage_after = {"session": 0.001, "weekly": 0.001}
    composite = print_report(task, result, usage_before, usage_after)
    # cost_delta = 0.001, n_correct=1, scale=1000
    # cost_score = 1/(1+0.001*1000) = 1/2
    assert abs(composite - 0.5) < 1e-9
