"""Runner for yoker-test: execute test tasks through Yoker and collect metrics.

We use ``yoker.agent()`` directly (not ``yoker.process()``) because we need
the ``event_handler`` for ``StatsCollector`` to capture TurnEndEvent metrics.
``yoker.process()`` internally does the same thing but doesn't expose the
event handler.
"""

import sys
import time
from datetime import datetime
from typing import Any, cast

import yoker
from yoker.backends import create_backend
from yoker.events import Event, EventCallback, EventType, TurnEndEvent

from yoker_test.report import aggregate_results, summarize_overall
from yoker_test.schema import RunMetadata, TestReport, TestResult, TestTask
from yoker_test.scorers import SCORERS, normalize_score_result
from yoker_test.usage import fetch_usage_metrics


def _model_requests(snapshot: dict, model: str) -> int:
  """Request count for the run's model; payload names lack the "-cloud" suffix."""
  counts: dict[str, int] = snapshot.get("requests") or {}
  base = model.removesuffix(":cloud").removesuffix("-cloud")
  return int(counts.get(base) or counts.get(model) or 0)


def _usage_deltas(
  before: dict | None,
  after: dict | None,
  model: str,
) -> tuple[dict[str, float] | None, int | None, float | None]:
  """Deltas between two usage snapshots: (quota fractions, requests, extra-usage cost).

  A window with a negative delta (quota window reset mid-run) is dropped
  individually; requests go None when negative (same reset). None inputs →
  all None.
  """
  if before is None or after is None:
    return None, None, None
  delta = {w: after[w] - before[w] for w in ("session", "weekly") if after[w] - before[w] >= 0}
  requests = _model_requests(after, model) - _model_requests(before, model)
  cb = before.get("extra_usage_cost")
  ca = after.get("extra_usage_cost")
  cost = ca - cb if cb is not None and ca is not None and ca >= cb else None
  return (delta or None), (requests if requests >= 0 else None), cost


def _fractions(snapshot: dict | None) -> dict[str, float] | None:
  """Quota fractions only — the persisted snapshot shape (schema field type)."""
  if snapshot is None:
    return None
  return {k: snapshot[k] for k in ("session", "weekly") if k in snapshot}


class StatsCollector:
  """Captures stats and text from an agent's event stream.

  Splits the output into thinking and content by collecting chunk events
  alongside the final TurnEndEvent token counts. Also captures TURN_START
  and CONTENT_START timestamps for TTFT (time to first token) measurement.
  """

  def __init__(self) -> None:
    self.stats: dict[str, Any] = {}
    self.thinking_chars: int = 0
    self.content_chars: int = 0
    self.turn_start_time: float | None = None
    self.content_start_time: float | None = None

  def __call__(self, event: Event) -> None:
    if event.type == EventType.TURN_START:
      self.turn_start_time = time.perf_counter()
    elif event.type == EventType.CONTENT_START:
      self.content_start_time = time.perf_counter()
    elif event.type == EventType.TURN_END:
      e: TurnEndEvent = event  # type: ignore[assignment]
      self.stats = {
        "input_tokens": e.input_tokens or 0,
        "output_tokens": e.output_tokens or 0,
        "prompt_eval_count": e.prompt_eval_count or 0,
        "eval_count": e.eval_count or 0,
        "total_duration_ms": e.total_duration_ms or 0,
      }
    elif event.type == EventType.THINKING_CHUNK:
      self.thinking_chars += len(event.text)  # type: ignore[attr-defined]
    elif event.type == EventType.CONTENT_CHUNK:
      self.content_chars += len(event.text)  # type: ignore[attr-defined]

  @property
  def ttft_ms(self) -> float | None:
    """Time to first token: from TURN_START to CONTENT_START.

    Returns None if either timestamp was not captured.
    """
    if self.turn_start_time is not None and self.content_start_time is not None:
      return (self.content_start_time - self.turn_start_time) * 1000
    return None


async def run_single_test(task: TestTask, config: Any, backend: Any = None) -> TestResult:
  """Execute one test task through Yoker, score it, return metrics.

  When ``backend`` is provided the agent reuses it instead of constructing a
  fresh one (shared across a run to avoid per-test backend/env churn).
  """
  collector = StatsCollector()

  agent = yoker.agent(
    config=config,
    tools=None,
    system_prompt=None,
    console_logging=False,
    event_handler=cast(EventCallback, collector),
    backend=backend,
  )

  t0 = time.perf_counter()
  error: str | None = None
  try:
    response = await agent.process(task.prompt)
  except Exception as exc:
    response = ""
    error = str(exc)
  finally:
    await agent.aclose()
  wall_ms = (time.perf_counter() - t0) * 1000

  # Normalize tokens: prefer OpenAI/Anthropic fields, fall back to Ollama
  s = collector.stats
  tokens_in = s.get("input_tokens") or s.get("prompt_eval_count") or 0
  tokens_out = s.get("output_tokens") or s.get("eval_count") or 0
  # Latency: prefer backend-reported, fall back to wall-clock
  latency_ms = s.get("total_duration_ms") or wall_ms

  # Score
  score: float = 0.0
  extracted: str | None = None
  sub_scores: dict[str, float] | None = None
  if error is None:
    if callable(task.scorer):
      scorer = task.scorer
    else:
      scorer = SCORERS[task.scorer]
    score, extracted, sub_scores = normalize_score_result(scorer(task, response))

  return TestResult(
    task_id=task.id,
    category=task.category,
    score=score,
    response=response.strip(),
    extracted=extracted,
    tokens_in=tokens_in,
    tokens_out=tokens_out,
    latency_ms=latency_ms,
    thinking_chars=collector.thinking_chars,
    content_chars=collector.content_chars,
    error=error,
    sub_scores=sub_scores,
    expected=task.expected,
  )


class EvalRunner:
  """Orchestrates multi-task × multi-repeat evaluation through Yoker.

  Executes each task for the configured number of repeats, collects metrics
  via StatsCollector, scores responses, and assembles a TestReport.

  The runner is stateless between ``run()`` calls — all per-run state is
  local to ``run()``. This makes the runner reusable across models.

  Execution is sequential (not concurrent) to ensure:
  1. Latency measurements are not affected by concurrent requests.
  2. Rate limits are not hit.
  3. The agent's internal serialization queue is not a bottleneck.

  TTFT (time to first token) is collected via TURN_START and CONTENT_START
  events in the StatsCollector. No backend.chat_stream() path is needed.

  Full refusal detection is deferred to P2.12. P2.4 detects only empty
  responses as likely refusals.

  Aggregation (summary/overall) is computed in run() via aggregate_results
  and summarize_overall.
  """

  def __init__(
    self,
    tasks: list[TestTask],
    repeats: int = 3,
    temperature: float = 0.0,
    seed: int = 42,
    suite_name: str = "",
    suite_version: str = "",
    aggregation_weights: dict[str, float] | None = None,
  ) -> None:
    self._tasks = tasks
    self._repeats = repeats
    self._temperature = temperature
    self._seed = seed
    self._suite_name = suite_name
    self._suite_version = suite_version
    self._weights = aggregation_weights

  async def run(self, model: str, config: Any) -> TestReport:
    """Execute all tasks × repeats, return a TestReport.

    Args:
      model: The model identifier to evaluate.
      config: A yoker Config instance (typed as Any to avoid hard dependency).

    Returns:
      TestReport with results, metadata, category summaries, and overall.

    Usage snapshots: backend is created once per run and shared by every
    agent. Per-execution snapshot pairs sit strictly outside timed sections
    and share consecutive edges (each execution's "before" is the previous
    "after"), so a run costs ~N+1 fetches. After 3 consecutive unavailable
    snapshots, snapshotting is disabled for the remainder of the run
    (circuit breaker — the usage API may be down, non-Ollama, or keyless).
    """
    config.backend.config.model = model
    backend = create_backend(config)

    results: list[TestResult] = []
    total = len(self._tasks) * self._repeats
    idx = 0

    prev: dict | None = None  # shared snapshot edge between executions
    first: dict | None = None  # run-level aggregate = first before / last after
    last: dict | None = None
    failures = 0
    snapshots_enabled = True

    async def take() -> dict | None:
      """One snapshot, None on failure; trips the breaker after 3 misses."""
      nonlocal failures, snapshots_enabled
      if not snapshots_enabled:
        return None
      snap = await fetch_usage_metrics(backend)
      if snap is None:
        failures += 1
        if failures >= 3:
          snapshots_enabled = False
      else:
        failures = 0
      return snap

    for task in self._tasks:
      for repeat in range(self._repeats):
        idx += 1
        print(
          f"[{idx}/{total}] {task.id} r{repeat}... ",
          end="",
          flush=True,
          file=sys.stderr,
        )

        # Snapshot pair strictly outside the timed section (latency/TTFT
        # untouched). Shared edges: next "before" reuses the previous "after".
        before = prev
        if before is None:
          before = await take()
          if before is not None and first is None:
            first = before

        result = await self._execute_once(task, repeat, config, backend)

        after = await take()
        if after is not None:
          last = after
        usage_delta, requests_delta, _ = _usage_deltas(before, after, model)
        result.usage_delta = usage_delta
        result.requests_delta = requests_delta
        prev = after  # may be None (fetch failed) — next pair degrades honestly

        results.append(result)
        if result.error:
          print(f"FAIL ({result.error})", file=sys.stderr)
        else:
          print(f"score={result.score:.1f}", file=sys.stderr)

    metadata = self._build_metadata(model, config)
    summary = aggregate_results(results, self._weights)

    run_delta, run_requests, run_cost = _usage_deltas(first, last, model)
    overall = summarize_overall(results, summary, self._weights, usage_delta=run_delta)
    overall.usage_note = self._usage_note(run_delta, first, last) if results else None
    overall.usage_before = _fractions(first)
    overall.usage_after = _fractions(last)
    overall.requests_delta = run_requests
    overall.extra_usage_cost_delta = run_cost
    return TestReport(run=metadata, results=results, summary=summary, overall=overall)

  def _usage_note(
    self, delta: dict[str, float] | None, first: dict | None, last: dict | None
  ) -> str | None:
    """Annotation explaining unavailable or window-reset poisoned deltas."""
    if first is None or last is None:
      return "usage API unavailable"
    if delta is None:
      return "usage windows reset mid-run"
    for window in ("session", "weekly"):
      if last[window] < first[window]:
        return f"{window} window reset mid-run"
    return None

  async def _execute_once(
    self, task: TestTask, repeat: int, config: Any, backend: Any = None
  ) -> TestResult:
    """Execute one task for one repeat. Errors don't propagate.

    One task failure does NOT abort the suite — the outer loop continues
    to the next task/repeat.
    """
    collector = StatsCollector()
    agent = yoker.agent(
      config=config,
      tools=None,
      system_prompt=task.system_prompt,
      console_logging=False,
      event_handler=cast(EventCallback, collector),
      backend=backend,
    )
    try:
      t0 = time.perf_counter()
      response = await agent.process(task.prompt)
      wall_ms = (time.perf_counter() - t0) * 1000

      # Normalize tokens: prefer OpenAI/Anthropic fields, fall back to Ollama
      s = collector.stats
      tokens_in = s.get("input_tokens") or s.get("prompt_eval_count") or 0
      tokens_out = s.get("output_tokens") or s.get("eval_count") or 0
      # Latency: prefer backend-reported, fall back to wall-clock
      latency_ms = s.get("total_duration_ms") or wall_ms
      # TTFT: from TURN_START to CONTENT_START timestamps
      ttft = collector.ttft_ms

      # Detect refusal (minimal — full detection deferred to P2.12)
      if not response.strip():
        return TestResult(
          task_id=task.id,
          category=task.category,
          score=0.0,
          response="",
          error="refused: empty response",
          difficulty=task.difficulty,
          repeat=repeat,
          prompt=task.prompt,
          expected=task.expected,
          tokens_in=tokens_in,
          tokens_out=tokens_out,
          latency_ms=latency_ms,
          thinking_chars=collector.thinking_chars,
          content_chars=collector.content_chars,
          ttft_ms=ttft,
        )

      # Score
      if callable(task.scorer):
        scorer = task.scorer
      else:
        scorer = SCORERS[task.scorer]
      score, extracted, sub_scores = normalize_score_result(scorer(task, response))
      scorer_name = (
        task.scorer if isinstance(task.scorer, str) else getattr(task.scorer, "__name__", "custom")
      )

      return TestResult(
        task_id=task.id,
        category=task.category,
        score=score,
        response=response.strip(),
        extracted=extracted,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        thinking_chars=collector.thinking_chars,
        content_chars=collector.content_chars,
        error=None,
        difficulty=task.difficulty,
        repeat=repeat,
        prompt=task.prompt,
        expected=task.expected,
        scorer_name=scorer_name,
        sub_scores=sub_scores,
        ttft_ms=ttft,
      )
    except Exception as exc:
      return TestResult(
        task_id=task.id,
        category=task.category,
        score=0.0,
        response="",
        error=str(exc),
        difficulty=task.difficulty,
        repeat=repeat,
        prompt=task.prompt,
        expected=task.expected,
      )
    finally:
      await agent.aclose()

  def _build_metadata(self, model: str, config: Any) -> RunMetadata:
    """Collect run metadata from config and runner state."""
    return RunMetadata(
      suite=self._suite_name,
      suite_version=self._suite_version,
      model=model,
      provider=getattr(config.backend, "provider", "unknown"),
      yoker_version=yoker.__version__,
      temperature=self._temperature,
      seed=self._seed,
      repeats=self._repeats,
      timestamp=datetime.now().isoformat(),
    )
