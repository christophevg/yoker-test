"""CLI for yoker-test: argument parsing and test orchestration."""

import argparse
import asyncio
import sys

from yoker.config import get_yoker_config

from yoker_test.report import print_report
from yoker_test.runner import run_single_test
from yoker_test.schema import TestTask
from yoker_test.usage import fetch_ollama_usage


async def async_main(model: str) -> int:
  """Run a single hardcoded MCQ task and print results."""
  task = TestTask(
    id="K1",
    category="knowledge",
    difficulty="easy",
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

  config = get_yoker_config()
  config.backend.config.model = model
  config.backend.validate()

  usage_before = await fetch_ollama_usage(config)

  print(f"yoker-test — model: {model}\n")
  print(f"  Task:   {task.id} ({task.category})")
  print(f"  Prompt: {task.prompt.splitlines()[0]}...")
  print()

  result = await run_single_test(task, config)

  usage_after = await fetch_ollama_usage(config)

  print_report(task, result, usage_before, usage_after)

  return 0 if result.error is None else 1


def main() -> None:
  """CLI entry point."""
  parser = argparse.ArgumentParser(description="yoker-test: model evaluation through Yoker")
  parser.add_argument("--model", default="glm-5.2:cloud", help="Model to test")
  args = parser.parse_args()
  sys.exit(asyncio.run(async_main(args.model)))
