#!/usr/bin/env python3
"""yoker-test main entry point.

Runs a hardcoded MCQ task through Yoker's SDK, scores it, and prints
multi-dimensional metrics (quality, efficiency, cost).

Usage:
  yoker-test --model glm-5.2:cloud
"""

import argparse
import asyncio
import sys
import time
from typing import Any

import yoker
from yoker.config import get_yoker_config
from yoker.events import Event, EventType, TurnEndEvent

from yoker_test.schema import TestResult, TestTask
from yoker_test.scorers import SCORERS
from yoker_test.usage import fetch_ollama_usage

# ── Stats collection ─────────────────────────────────────────────────────


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


# ── Runner ───────────────────────────────────────────────────────────────


async def run_single_test(task: TestTask, config: Any) -> TestResult:
  """Execute one test task through Yoker, score it, return metrics."""
  collector = StatsCollector()

  agent = yoker.agent(
    config=config,
    tools=None,
    system_prompt=None,
    console_logging=False,
    event_handler=collector,
  )

  t0 = time.monotonic()
  try:
    response = await agent.process(task.prompt)
  except Exception as exc:
    response = ""
    error = str(exc)
  else:
    error = None
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


# ── Composite score ──────────────────────────────────────────────────────


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


# ── Main ─────────────────────────────────────────────────────────────────


async def async_main(model: str) -> int:
  # One hardcoded MCQ task
  task = TestTask(
    id="K1",
    category="knowledge",
    prompt=(
      "Question: What is the chemical symbol for gold?\n"
      "A) Gd\n"
      "B) Go\n"
      "C) Au\n"
      "D) Ag\n"
      "Reply with only the letter of the correct answer."
    ),
    expected="C",
    scorer="mcq",
  )

  # Load config, apply model override
  config = get_yoker_config()
  config.backend.config.model = model
  config.backend.validate()

  # Fetch usage before the test
  usage_before = await fetch_ollama_usage(config)

  print(f"yoker-test — model: {model}\n")
  print(f"  Task:   {task.id} ({task.category})")
  print(f"  Prompt: {task.prompt.splitlines()[0]}...")
  print()

  result = await run_single_test(task, config)

  # Fetch usage after the test
  usage_after = await fetch_ollama_usage(config)

  # Report
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
  if usage_before and usage_after:
    session_delta = usage_after["session"] - usage_before["session"]
    weekly_delta = usage_after["weekly"] - usage_before["weekly"]
    sb, sa, sd = usage_before["session"] * 100, usage_after["session"] * 100, session_delta * 100
    wb, wa, wd = usage_before["weekly"] * 100, usage_after["weekly"] * 100, weekly_delta * 100
    print(f"  Session:    {sb:.4f}% → {sa:.4f}% ({'+' if sd >= 0 else ''}{sd:.4f}%)")
    print(f"  Weekly:     {wb:.4f}% → {wa:.4f}% ({'+' if wd >= 0 else ''}{wd:.4f}%)")
  else:
    session_delta = None

  # Composite score
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

  return 0 if result.error is None else 1


def main() -> None:
  """CLI entry point."""
  parser = argparse.ArgumentParser(description="yoker-test: model evaluation through Yoker")
  parser.add_argument("--model", default="glm-5.2:cloud", help="Model to test")
  args = parser.parse_args()
  sys.exit(asyncio.run(async_main(args.model)))
