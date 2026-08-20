"""Report generation for yoker-test: composite scoring and output formatting."""

from yoker_test.schema import TestResult, TestTask


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
