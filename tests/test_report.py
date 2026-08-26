"""Tests for yoker_test.report."""

import math

import pytest

from yoker_test.report import (
  aggregate_results,
  compare_baseline,
  compute_composite,
  format_console_report,
  format_quality_ranking,
  print_report,
  summarize_overall,
)
from yoker_test.schema import (
  CategorySummary,
  ComparisonReport,
  OverallSummary,
  RunMetadata,
  TestReport,
  TestResult,
  TestTask,
)


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
    assert abs(composite - 0.5) < 1e-9


# -- Helper factories for aggregation/comparison/formatting tests --


def _result(
  task_id: str = "K1",
  category: str = "knowledge",
  score: float = 1.0,
  tokens_in: int | None = 100,
  tokens_out: int | None = 50,
  latency_ms: float = 500.0,
  difficulty: str = "easy",
  repeat: int = 0,
  error: str | None = None,
) -> TestResult:
  return TestResult(
    task_id=task_id,
    category=category,
    score=score,
    response="x",
    tokens_in=tokens_in,
    tokens_out=tokens_out,
    latency_ms=latency_ms,
    difficulty=difficulty,
    repeat=repeat,
    error=error,
  )


def _run_metadata(model: str = "test-model") -> RunMetadata:
  return RunMetadata(
    suite="test-suite",
    suite_version="1.0.0",
    model=model,
    provider="ollama",
    yoker_version="0.10.1",
    temperature=0.0,
    seed=42,
    repeats=1,
    timestamp="2025-01-01T00:00:00",
  )


def _category_summary(
  score: float = 0.75,
  std: float = 0.05,
  n_tasks: int = 2,
  avg_tokens_in: float = 100,
  avg_tokens_out: float = 50,
  avg_latency_ms: float = 500,
  total_tokens: int = 300,
  total_latency_s: float = 1.0,
) -> CategorySummary:
  return CategorySummary(
    score=score,
    std=std,
    n_tasks=n_tasks,
    avg_tokens_in=avg_tokens_in,
    avg_tokens_out=avg_tokens_out,
    avg_latency_ms=avg_latency_ms,
    total_tokens=total_tokens,
    total_latency_s=total_latency_s,
  )


def _overall_summary(
  score: float = 0.75,
  std: float = 0.03,
  total_tokens_in: int = 200,
  total_tokens_out: int = 100,
  total_tokens: int = 300,
  total_latency_s: float = 1.0,
  avg_tokens_per_second: float = 100.0,
  usage_delta: dict[str, float] | None = None,
) -> OverallSummary:
  return OverallSummary(
    score=score,
    std=std,
    total_tokens_in=total_tokens_in,
    total_tokens_out=total_tokens_out,
    total_tokens=total_tokens,
    total_latency_s=total_latency_s,
    avg_tokens_per_second=avg_tokens_per_second,
    usage_delta=usage_delta,
  )


def _test_report(
  run: RunMetadata | None = None,
  results: list[TestResult] | None = None,
  summary: dict[str, CategorySummary] | None = None,
  overall: OverallSummary | None = None,
  comparison: ComparisonReport | None = None,
) -> TestReport:
  return TestReport(
    run=run or _run_metadata(),
    results=results if results is not None else [],
    summary=summary if summary is not None else {},
    overall=overall,
    comparison=comparison,
  )


class TestAggregateResults:
  """Tests for aggregate_results."""

  def test_correct_mean_and_std(self):
    results = [
      _result(score=1.0),
      _result(score=0.0),
    ]
    summaries = aggregate_results(results)
    assert summaries["knowledge"].score == 0.5
    assert abs(summaries["knowledge"].std - 0.7071) < 1e-3  # sample stdev of [1.0, 0.0]
    assert summaries["knowledge"].n_tasks == 2

  def test_multiple_categories(self):
    results = [
      _result(task_id="K1", category="knowledge", score=1.0),
      _result(task_id="R1", category="reasoning", score=0.5),
    ]
    summaries = aggregate_results(results)
    assert set(summaries.keys()) == {"knowledge", "reasoning"}
    assert summaries["knowledge"].score == 1.0
    assert summaries["reasoning"].score == 0.5

  def test_none_tokens_treated_as_zero(self):
    results = [
      _result(tokens_in=None, tokens_out=None),
      _result(tokens_in=100, tokens_out=50),
    ]
    summaries = aggregate_results(results)
    assert summaries["knowledge"].avg_tokens_in == 50.0
    assert summaries["knowledge"].avg_tokens_out == 25.0
    assert summaries["knowledge"].total_tokens == 150

  def test_single_result_has_zero_std(self):
    results = [_result(score=0.8)]
    summaries = aggregate_results(results)
    assert summaries["knowledge"].std == 0.0
    assert summaries["knowledge"].n_tasks == 1

  def test_empty_results_returns_empty_dict(self):
    assert aggregate_results([]) == {}

  def test_total_tokens_and_latency(self):
    results = [
      _result(tokens_in=100, tokens_out=50, latency_ms=1000.0),
      _result(tokens_in=200, tokens_out=100, latency_ms=3000.0),
    ]
    summaries = aggregate_results(results)
    assert summaries["knowledge"].total_tokens == 450
    assert summaries["knowledge"].total_latency_s == 4.0
    assert summaries["knowledge"].avg_latency_ms == 2000.0

  def test_weights_parameter_ignored(self):
    """weights is accepted but not used in per-category aggregation."""
    results = [_result(score=1.0), _result(score=0.0)]
    with_weights = aggregate_results(results, weights={"knowledge": 0.9})
    without_weights = aggregate_results(results)
    assert with_weights == without_weights


class TestSummarizeOverall:
  """Tests for summarize_overall."""

  def test_equal_weighting(self):
    results = [
      _result(category="knowledge", score=0.5),
      _result(category="reasoning", score=1.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries)
    assert abs(overall.score - 0.75) < 1e-9  # (0.5 + 1.0) / 2
    assert overall.usage_delta is None

  def test_weighted_average(self):
    results = [
      _result(category="knowledge", score=0.5),
      _result(category="reasoning", score=1.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries, weights={"knowledge": 0.7, "reasoning": 0.3})
    expected = 0.5 * 0.7 + 1.0 * 0.3
    assert abs(overall.score - expected) < 1e-9

  def test_weight_normalization(self):
    results = [
      _result(category="knowledge", score=0.5),
      _result(category="reasoning", score=1.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries, weights={"knowledge": 7.0, "reasoning": 3.0})
    expected = 0.5 * 0.7 + 1.0 * 0.3
    assert abs(overall.score - expected) < 1e-9

  def test_weights_sum_to_zero_falls_back_to_equal(self):
    results = [
      _result(category="knowledge", score=0.5),
      _result(category="reasoning", score=1.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries, weights={"knowledge": 0.0, "reasoning": 0.0})
    assert abs(overall.score - 0.75) < 1e-9

  def test_category_not_in_weights_excluded(self):
    results = [
      _result(category="knowledge", score=0.5),
      _result(category="reasoning", score=1.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries, weights={"knowledge": 1.0})
    assert abs(overall.score - 0.5) < 1e-9

  def test_usage_delta_passthrough(self):
    results = [_result(score=0.8)]
    summaries = aggregate_results(results)
    usage = {"session": 0.15, "weekly": 0.30}
    overall = summarize_overall(results, summaries, usage_delta=usage)
    assert overall.usage_delta == usage

  def test_zero_latency_throughput_zero(self):
    results = [_result(score=0.8, latency_ms=0.0)]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries)
    assert overall.avg_tokens_per_second == 0.0

  def test_throughput_uses_output_tokens(self):
    results = [
      _result(tokens_in=100, tokens_out=50, latency_ms=1000.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries)
    assert abs(overall.avg_tokens_per_second - 50.0) < 1e-9

  def test_empty_results_returns_zeros(self):
    overall = summarize_overall([], {})
    assert overall.score == 0.0
    assert overall.std == 0.0
    assert overall.total_tokens == 0
    assert overall.total_latency_s == 0.0
    assert overall.avg_tokens_per_second == 0.0

  def test_weighted_std_propagation(self):
    results = [
      _result(category="a", score=1.0),
      _result(category="a", score=0.0),
      _result(category="b", score=1.0),
      _result(category="b", score=0.0),
    ]
    summaries = aggregate_results(results)
    overall = summarize_overall(results, summaries, weights={"a": 0.5, "b": 0.5})
    expected_std = math.sqrt((0.7071 * 0.5) ** 2 + (0.7071 * 0.5) ** 2)
    assert abs(overall.std - expected_std) < 1e-3


class TestCompareBaseline:
  """Tests for compare_baseline."""

  def test_correct_deltas(self):
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.8)},
      overall=_overall_summary(score=0.8),
    )
    baseline = _test_report(
      run=_run_metadata(model="baseline-model"),
      summary={"knowledge": _category_summary(score=0.6)},
      overall=_overall_summary(score=0.6),
    )
    comp = compare_baseline(current, baseline)
    assert comp.delta["knowledge"] == pytest.approx(0.2)
    assert comp.delta["overall"] == pytest.approx(0.2)
    assert comp.baseline.model == "baseline-model"

  def test_flagging_at_two_std(self):
    # delta=0.2, std=0.05 → 0.2 > 2*0.05=0.1 → flagged
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.8, std=0.05)},
    )
    baseline = _test_report(
      summary={"knowledge": _category_summary(score=0.6, std=0.05)},
    )
    comp = compare_baseline(current, baseline)
    assert "knowledge" in comp.flagged

  def test_no_flag_when_within_two_std(self):
    # delta=0.05, std=0.05 → 0.05 < 2*0.05=0.1 → not flagged
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.65, std=0.05)},
    )
    baseline = _test_report(
      summary={"knowledge": _category_summary(score=0.6, std=0.05)},
    )
    comp = compare_baseline(current, baseline)
    assert "knowledge" not in comp.flagged

  def test_std_zero_flags_any_nonzero_delta(self):
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.8, std=0.0)},
    )
    baseline = _test_report(
      summary={"knowledge": _category_summary(score=0.6, std=0.0)},
    )
    comp = compare_baseline(current, baseline)
    assert "knowledge" in comp.flagged

  def test_std_zero_no_flag_when_zero_delta(self):
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.8, std=0.0)},
    )
    baseline = _test_report(
      summary={"knowledge": _category_summary(score=0.8, std=0.0)},
    )
    comp = compare_baseline(current, baseline)
    assert "knowledge" not in comp.flagged

  def test_missing_category_in_baseline_skipped(self):
    current = _test_report(
      summary={
        "knowledge": _category_summary(score=0.8),
        "reasoning": _category_summary(score=0.5),
      },
    )
    baseline = _test_report(
      summary={"knowledge": _category_summary(score=0.6)},
    )
    comp = compare_baseline(current, baseline)
    assert "knowledge" in comp.delta
    assert "reasoning" not in comp.delta

  def test_missing_overall_skips_overall_delta(self):
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.8)},
      overall=None,
    )
    baseline = _test_report(
      summary={"knowledge": _category_summary(score=0.6)},
      overall=_overall_summary(score=0.6),
    )
    comp = compare_baseline(current, baseline)
    assert "overall" not in comp.delta

  def test_empty_baseline_summary(self):
    current = _test_report(
      summary={"knowledge": _category_summary(score=0.8)},
      overall=_overall_summary(score=0.8),
    )
    baseline = _test_report(
      summary={},
      overall=_overall_summary(score=0.6),
    )
    comp = compare_baseline(current, baseline)
    assert "knowledge" not in comp.delta
    assert "overall" in comp.delta


class TestFormatConsoleReport:
  """Tests for format_console_report."""

  def test_all_sections_present(self):
    report = _test_report(
      results=[_result(task_id="K1", category="knowledge", score=1.0)],
      summary={"knowledge": _category_summary(score=0.75, std=0.05, n_tasks=1)},
      overall=_overall_summary(score=0.75, usage_delta={"session": 0.1}),
    )
    output = format_console_report(report)
    assert "Suite:" in output
    assert "Model:" in output
    assert "Provider:" in output
    assert "Yoker:" in output
    assert "Time:" in output
    assert "[knowledge]" in output
    assert "K1" in output
    assert "Category" in output
    assert "knowledge" in output
    assert "Overall" in output
    assert "Score:" in output
    assert "Throughput:" in output
    assert "Usage Δ:" in output

  def test_empty_results(self):
    report = _test_report(results=[])
    output = format_console_report(report)
    assert "No results." in output

  def test_missing_overall_skips_section(self):
    report = _test_report(
      results=[_result()],
      summary={"knowledge": _category_summary()},
      overall=None,
    )
    output = format_console_report(report)
    assert "Overall" not in output

  def test_missing_comparison_skips_section(self):
    report = _test_report(
      results=[_result()],
      summary={"knowledge": _category_summary()},
      overall=_overall_summary(),
      comparison=None,
    )
    output = format_console_report(report)
    assert "Comparison" not in output

  def test_comparison_section_present(self):
    comp = ComparisonReport(
      baseline=_run_metadata(model="old-model"),
      delta={"knowledge": -0.1, "overall": -0.05},
      flagged=["knowledge"],
    )
    report = _test_report(
      results=[_result()],
      summary={"knowledge": _category_summary()},
      overall=_overall_summary(),
      comparison=comp,
    )
    output = format_console_report(report)
    assert "Comparison" in output
    assert "old-model" in output
    assert "knowledge" in output

  def test_error_indicator_in_task_detail(self):
    report = _test_report(
      results=[_result(error="Connection failed")],
    )
    output = format_console_report(report)
    assert "ERR" in output

  def test_empty_summary(self):
    report = _test_report(
      results=[_result()],
      summary={},
    )
    output = format_console_report(report)
    assert "No category summaries available." in output


class TestFormatQualityRanking:
  """Tests for format_quality_ranking."""

  def test_sort_order_descending_by_score(self):
    reports = [
      _test_report(
        run=_run_metadata(model="model-b"),
        overall=_overall_summary(score=0.5),
      ),
      _test_report(
        run=_run_metadata(model="model-a"),
        overall=_overall_summary(score=0.9),
      ),
    ]
    output = format_quality_ranking(reports)
    lines = output.strip().split("\n")
    assert "model-a" in lines[1]
    assert "model-b" in lines[2]

  def test_missing_overall_raises_value_error(self):
    reports = [
      _test_report(run=_run_metadata(model="model-x"), overall=None),
    ]
    with pytest.raises(ValueError, match="lack overall summaries"):
      format_quality_ranking(reports)

  def test_empty_list_returns_message(self):
    assert format_quality_ranking([]) == "No reports to rank."

  def test_tie_breaking_by_model_name(self):
    reports = [
      _test_report(
        run=_run_metadata(model="zzz-model"),
        overall=_overall_summary(score=0.75),
      ),
      _test_report(
        run=_run_metadata(model="aaa-model"),
        overall=_overall_summary(score=0.75),
      ),
    ]
    output = format_quality_ranking(reports)
    lines = output.strip().split("\n")
    assert "aaa-model" in lines[1]
    assert "zzz-model" in lines[2]

  def test_single_report_still_shows_table(self):
    reports = [
      _test_report(
        run=_run_metadata(model="only-model"),
        overall=_overall_summary(score=0.8),
      ),
    ]
    output = format_quality_ranking(reports)
    assert "only-model" in output
    assert "1" in output

  def test_usage_delta_displayed(self):
    reports = [
      _test_report(
        run=_run_metadata(model="model-a"),
        overall=_overall_summary(score=0.9, usage_delta={"session": 0.15}),
      ),
    ]
    output = format_quality_ranking(reports)
    assert "0.15%" in output

  def test_usage_delta_na_when_missing(self):
    reports = [
      _test_report(
        run=_run_metadata(model="model-a"),
        overall=_overall_summary(score=0.9, usage_delta=None),
      ),
    ]
    output = format_quality_ranking(reports)
    assert "N/A" in output

  def test_reports_without_overall_skipped(self):
    reports = [
      _test_report(run=_run_metadata(model="no-overall"), overall=None),
      _test_report(
        run=_run_metadata(model="has-overall"),
        overall=_overall_summary(score=0.8),
      ),
    ]
    output = format_quality_ranking(reports)
    assert "has-overall" in output
    assert "no-overall" not in output


class TestBackwardCompatibility:
  """Ensure existing compute_composite and print_report tests still pass."""

  def test_compute_composite_still_works(self):
    assert compute_composite(quality=0.8, cost_delta=None, n_tasks=10, n_correct=8) == 0.8

  def test_print_report_still_works(self, capsys):
    task = make_task()
    result = make_result()
    composite = print_report(task, result, None, None)
    assert composite == 1.0
