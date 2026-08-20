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

from yoker.config import get_yoker_config

from yoker_test.report import print_report
from yoker_test.runner import run_single_test
from yoker_test.schema import TestTask
from yoker_test.usage import fetch_ollama_usage

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

  print_report(task, result, usage_before, usage_after)

  return 0 if result.error is None else 1


def main() -> None:
  """CLI entry point."""
  parser = argparse.ArgumentParser(description="yoker-test: model evaluation through Yoker")
  parser.add_argument("--model", default="glm-5.2:cloud", help="Model to test")
  args = parser.parse_args()
  sys.exit(asyncio.run(async_main(args.model)))
