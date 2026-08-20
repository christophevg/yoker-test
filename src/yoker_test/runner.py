"""Runner for yoker-test: execute test tasks through Yoker and collect metrics."""

import time
from typing import Any, cast

import yoker
from yoker.events import Event, EventCallback, EventType, TurnEndEvent

from yoker_test.schema import TestResult, TestTask
from yoker_test.scorers import SCORERS


class StatsCollector:
  """Captures stats and text from an agent's event stream.

  Splits the output into thinking and content by collecting chunk events
  alongside the final TurnEndEvent token counts.
  """

  def __init__(self) -> None:
    self.stats: dict[str, Any] = {}
    self.thinking_chars: int = 0
    self.content_chars: int = 0

  def __call__(self, event: Event) -> None:
    if event.type == EventType.TURN_END:
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


async def run_single_test(task: TestTask, config: Any) -> TestResult:
  """Execute one test task through Yoker, score it, return metrics."""
  collector = StatsCollector()

  agent = yoker.agent(
    config=config,
    tools=None,
    system_prompt=None,
    console_logging=False,
    event_handler=cast(EventCallback, collector),
  )

  t0 = time.monotonic()
  error: str | None = None
  try:
    response = await agent.process(task.prompt)
  except Exception as exc:
    response = ""
    error = str(exc)
  wall_ms = (time.monotonic() - t0) * 1000

  # Normalize tokens: prefer OpenAI/Anthropic fields, fall back to Ollama
  s = collector.stats
  tokens_in = s.get("input_tokens") or s.get("prompt_eval_count") or 0
  tokens_out = s.get("output_tokens") or s.get("eval_count") or 0
  # Latency: prefer backend-reported, fall back to wall-clock
  latency_ms = s.get("total_duration_ms") or wall_ms

  # Score
  score, extracted = (0.0, None)
  if error is None:
    if callable(task.scorer):
      scorer = task.scorer
    else:
      scorer = SCORERS[task.scorer]
    score, extracted = scorer(task, response)

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
  )
