"""Report generation for yoker-test: composite scoring and output formatting."""

import math
import statistics
from collections import defaultdict

from yoker_test.schema import (
  CategorySummary,
  ComparisonReport,
  OverallSummary,
  TestReport,
  TestResult,
  TestTask,
)


def compute_composite(
  quality: float,
  cost_delta: float | None,
  n_tasks: int,
  n_correct: float,
  scale: float = 1000.0,
) -> float:
  """Compute a composite yoker-test score (0.0–1.0).

  Formula: composite = quality × cost_score

  - quality: overall score (0.0–1.0), the floor — wrong answers can't be
    "cheap enough" to score well.
  - cost_score: 1 / (1 + cost_per_correct × scale), where
    cost_per_correct = cost_delta / max(n_correct, 1).
    Free models (cost_delta=0) → cost_score=1.0 → composite=quality.
    Expensive models need higher quality to justify their cost.

  Args:
    quality: overall quality score (0.0–1.0).
    cost_delta: API cost consumed during the run (e.g. session usage delta).
      None if cost tracking unavailable → cost_score defaults to 1.0.
    n_tasks: number of tasks in the suite.
    n_correct: expected number of correct answers (quality × n_tasks).
    scale: scaling factor for cost_per_correct. 1000 means 0.1% cost per
      correct answer yields cost_score ≈ 0.5.

  Returns:
    Composite score (0.0–1.0).
  """
  if cost_delta is None or cost_delta <= 0 or n_correct < 1:
    cost_score = 1.0
  else:
    cost_per_correct = cost_delta / max(n_correct, 1)
    cost_score = 1.0 / (1.0 + cost_per_correct * scale)

  return quality * cost_score


def print_report(
  task: TestTask,
  result: TestResult,
  usage_before: dict[str, float] | None,
  usage_after: dict[str, float] | None,
) -> float:
  """Print test results and return the composite score.

  Args:
    task: The test task that was executed.
    result: The test result with metrics.
    usage_before: Ollama usage before the test, or None.
    usage_after: Ollama usage after the test, or None.

  Returns:
    The composite score (0.0–1.0).
  """
  total_chars = result.thinking_chars + result.content_chars
  print("─" * 50)
  print(f"  Score:      {result.score}")
  print(f"  Response:   {result.response!r}")
  print(f"  Extracted:  {result.extracted!r}")
  print(f"  Expected:   {task.expected!r}")
  print(f"  Tokens in:  {result.tokens_in}")
  print(f"  Tokens out: {result.tokens_out}")
  if total_chars > 0:
    thinking_pct = result.thinking_chars / total_chars * 100
    print(f"  Thinking:   {result.thinking_chars} chars ({thinking_pct:.0f}%)")
    print(f"  Content:    {result.content_chars} chars ({100 - thinking_pct:.0f}%)")
  else:
    print(f"  Thinking:   {result.thinking_chars} chars")
    print(f"  Content:    {result.content_chars} chars")
  print(f"  Latency:    {result.latency_ms:.0f} ms")

  session_delta = None
  if usage_before and usage_after:
    session_delta = usage_after["session"] - usage_before["session"]
    weekly_delta = usage_after["weekly"] - usage_before["weekly"]
    sb, sa, sd = usage_before["session"] * 100, usage_after["session"] * 100, session_delta * 100
    wb, wa, wd = usage_before["weekly"] * 100, usage_after["weekly"] * 100, weekly_delta * 100
    print(f"  Session:    {sb:.4f}% → {sa:.4f}% ({'+' if sd >= 0 else ''}{sd:.4f}%)")
    print(f"  Weekly:     {wb:.4f}% → {wa:.4f}% ({'+' if wd >= 0 else ''}{wd:.4f}%)")

  n_tasks = 1
  n_correct = result.score * n_tasks
  cost_delta = session_delta if session_delta is not None else None
  composite = compute_composite(
    quality=result.score,
    cost_delta=cost_delta,
    n_tasks=n_tasks,
    n_correct=n_correct,
  )
  print(f"  Composite:  {composite:.4f}")

  if result.error:
    print(f"  Error:      {result.error}")
  print("─" * 50)

  return composite


def aggregate_results(
  results: list[TestResult],
  weights: dict[str, float] | None = None,
) -> dict[str, CategorySummary]:
  """Group results by category and compute per-category statistics.

  The weights parameter is accepted for API symmetry with the TODO spec
  but is not used here — weighting is applied at the overall level by
  summarize_overall.

  Returns an empty dict for empty results. None tokens are treated as 0.
  Single-result categories get std=0.0 (sample stdev requires n>=2).
  """
  if not results:
    return {}

  by_category: dict[str, list[TestResult]] = defaultdict(list)
  for r in results:
    by_category[r.category].append(r)

  summaries: dict[str, CategorySummary] = {}
  for cat, cat_results in by_category.items():
    scores = [r.score for r in cat_results]
    n = len(cat_results)
    std = statistics.stdev(scores) if n > 1 else 0.0

    tokens_in = [r.tokens_in or 0 for r in cat_results]
    tokens_out = [r.tokens_out or 0 for r in cat_results]
    latencies = [r.latency_ms for r in cat_results]

    total_tok = sum(ti + to for ti, to in zip(tokens_in, tokens_out, strict=True))

    summaries[cat] = CategorySummary(
      score=statistics.mean(scores),
      std=std,
      n_tasks=n,
      avg_tokens_in=statistics.mean(tokens_in),
      avg_tokens_out=statistics.mean(tokens_out),
      avg_latency_ms=statistics.mean(latencies),
      total_tokens=total_tok,
      total_latency_s=sum(latencies) / 1000.0,
    )

  return summaries


def summarize_overall(
  results: list[TestResult],
  category_summaries: dict[str, CategorySummary],
  weights: dict[str, float] | None = None,
  usage_delta: dict[str, float] | None = None,
) -> OverallSummary:
  """Compute the overall summary across all categories.

  When weights is None, categories are equally weighted. When provided,
  weights are normalized to sum 1.0 and categories not listed get weight 0.
  If weights sum to 0, falls back to equal weighting.

  Throughput uses total_tokens_out (output generation speed, not input).
  """
  categories = list(category_summaries.keys())

  if not categories:
    return OverallSummary(
      score=0.0,
      std=0.0,
      total_tokens_in=0,
      total_tokens_out=0,
      total_tokens=0,
      total_latency_s=0.0,
      avg_tokens_per_second=0.0,
      usage_delta=usage_delta,
    )

  # Resolve weights: equal when None, normalized when provided
  if weights is None:
    w = {cat: 1.0 / len(categories) for cat in categories}
  else:
    total_w = sum(weights.get(cat, 0.0) for cat in categories)
    if total_w > 0:
      w = {cat: weights.get(cat, 0.0) / total_w for cat in categories}
    else:
      w = {cat: 1.0 / len(categories) for cat in categories}

  score = sum(category_summaries[cat].score * w[cat] for cat in categories)
  std = math.sqrt(sum((category_summaries[cat].std * w[cat]) ** 2 for cat in categories))

  total_tokens_in = sum(r.tokens_in or 0 for r in results)
  total_tokens_out = sum(r.tokens_out or 0 for r in results)
  total_tokens = total_tokens_in + total_tokens_out
  total_latency_s = sum(r.latency_ms for r in results) / 1000.0
  avg_tokens_per_second = total_tokens_out / total_latency_s if total_latency_s > 0 else 0.0

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


def compare_baseline(current: TestReport, baseline: TestReport) -> ComparisonReport:
  """Compare a current report against a baseline report.

  Computes per-category score deltas and an overall delta. Flags categories
  where |delta| > 2 × current's std. With std=0, any non-zero delta is flagged
  — zero variance with a changed score is a real signal.

  Missing categories on either side are skipped. Missing overall on either
  side skips the overall delta.
  """
  delta: dict[str, float] = {}
  flagged: list[str] = []

  for cat, cur_sum in current.summary.items():
    if cat not in baseline.summary:
      continue
    d = cur_sum.score - baseline.summary[cat].score
    delta[cat] = d
    if abs(d) > 2 * cur_sum.std:
      flagged.append(cat)

  if current.overall is not None and baseline.overall is not None:
    d = current.overall.score - baseline.overall.score
    delta["overall"] = d
    if abs(d) > 2 * current.overall.std:
      flagged.append("overall")

  return ComparisonReport(baseline=baseline.run, delta=delta, flagged=flagged)


def format_console_report(report: TestReport) -> str:
  """Format a TestReport as a multi-section plain text string.

  Sections: header, per-task detail (grouped by category), category summaries
  table, overall summary, comparison (if present). Returns the string without
  printing.
  """
  lines: list[str] = []

  # Header
  run = report.run
  lines.append(f"Suite:    {run.suite} (v{run.suite_version})")
  lines.append(f"Model:    {run.model}")
  lines.append(f"Provider: {run.provider}")
  lines.append(f"Yoker:    {run.yoker_version}")
  lines.append(f"Time:     {run.timestamp}")
  lines.append("")

  # Per-task detail
  if not report.results:
    lines.append("No results.")
    lines.append("")
  else:
    by_category: dict[str, list[TestResult]] = defaultdict(list)
    for r in report.results:
      by_category[r.category].append(r)
    for cat in sorted(by_category.keys()):
      lines.append(f"[{cat}]")
      for r in by_category[cat]:
        err = " ERR" if r.error else ""
        lines.append(
          f"  {r.task_id:<8} {r.difficulty:<6} r{r.repeat}  "
          f"score={r.score:.1f}  tokens={r.tokens_in or 0}+{r.tokens_out or 0}  "
          f"latency={r.latency_ms:.0f}ms{err}"
        )
      lines.append("")

  # Category summaries
  if not report.summary:
    lines.append("No category summaries available.")
    lines.append("")
  else:
    lines.append(
      f"{'Category':<14} {'Score':>6} {'Std':>6} {'N':>4} "
      f"{'Avg In':>7} {'Avg Out':>8} {'Avg Lat':>8} {'Total Tok':>10}"
    )
    for cat in sorted(report.summary.keys()):
      s = report.summary[cat]
      lines.append(
        f"{cat:<14} {s.score:>6.3f} {s.std:>6.3f} {s.n_tasks:>4} "
        f"{s.avg_tokens_in:>7.0f} {s.avg_tokens_out:>8.0f} "
        f"{s.avg_latency_ms:>7.0f}ms {s.total_tokens:>10}"
      )
    lines.append("")

  # Overall summary
  if report.overall is not None:
    o = report.overall
    lines.append("Overall")
    lines.append(f"  Score:      {o.score:.3f}")
    lines.append(f"  Std:        {o.std:.3f}")
    lines.append(
      f"  Tokens:     {o.total_tokens} (in={o.total_tokens_in}, out={o.total_tokens_out})"
    )
    lines.append(f"  Latency:    {o.total_latency_s:.1f}s")
    lines.append(f"  Throughput: {o.avg_tokens_per_second:.1f} tok/s")
    if o.usage_delta is not None:
      session = o.usage_delta.get("session", 0.0)
      lines.append(f"  Usage Δ:    {session:.2f}%")
    lines.append("")

  # Comparison
  if report.comparison is not None:
    comp = report.comparison
    lines.append(f"Comparison (baseline: {comp.baseline.model})")
    lines.append(f"{'Category':<14} {'Delta':>8} {'Flagged':>8}")
    for key in sorted(k for k in comp.delta if k != "overall"):
      flag = "⚠" if key in comp.flagged else ""
      lines.append(f"{key:<14} {comp.delta[key]:>+8.3f} {flag:>8}")
    if "overall" in comp.delta:
      flag = "⚠" if "overall" in comp.flagged else ""
      lines.append(f"{'overall':<14} {comp.delta['overall']:>+8.3f} {flag:>8}")
    lines.append("")

  return "\n".join(lines)


def format_quality_ranking(reports: list[TestReport]) -> str:
  """Rank multiple TestReports by overall quality score (descending).

  Reports without an overall summary are skipped. Raises ValueError if all
  reports lack overall summaries. Ties are broken by model name (alphabetical).
  """
  if not reports:
    return "No reports to rank."

  ranked = [r for r in reports if r.overall is not None]
  if not ranked:
    models = [r.run.model for r in reports]
    raise ValueError(
      f"All reports lack overall summaries — call summarize_overall first. "
      f"Models: {', '.join(models)}"
    )

  ranked.sort(key=lambda r: (-r.overall.score, r.run.model))  # type: ignore[union-attr]

  lines: list[str] = []
  lines.append(
    f"{'Rank':<5} {'Model':<24} {'Quality':>8} {'Std':>6} "
    f"{'Tokens':>8} {'Latency':>8} {'Usage Δ':>8}"
  )
  for i, r in enumerate(ranked, 1):
    assert r.overall is not None  # filtered above
    o = r.overall
    usage = (
      f"{o.usage_delta['session']:.2f}%" if o.usage_delta and "session" in o.usage_delta else "N/A"
    )
    lines.append(
      f"{i:<5} {r.run.model:<24} {o.score:>8.3f} {o.std:>6.3f} "
      f"{o.total_tokens:>8} {o.total_latency_s:>7.1f}s {usage:>8}"
    )

  return "\n".join(lines)
