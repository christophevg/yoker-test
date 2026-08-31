"""CLI for yoker-test: subcommands for suite-based model evaluation."""

import argparse
import asyncio
import sys
from pathlib import Path

from yoker_test.config import _resolve_suite_path, evaluate
from yoker_test.loader import load_suite, validate_suite
from yoker_test.report import format_console_report


async def cmd_eval(
  suite: str,
  model: str,
  compare: str | None,
  output: str | None,
  repeats: int | None,
  with_paths: list[str] | None = None,
  verbose: bool = False,
) -> int:
  """Run an evaluation suite and print/save the report."""
  for p in with_paths or []:
    if p not in sys.path:
      sys.path.insert(0, p)

  try:
    report = await evaluate(
      suite=suite, model=model, compare=compare, repeats=repeats, verbose=verbose
    )
  except (FileNotFoundError, ValueError) as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1

  # Detail already streamed live (stderr) when verbose; final report stays compact.
  print(format_console_report(report))

  if output is not None:
    path = Path(output)
    if path.suffix == ".json":
      content = report.to_json()
    else:
      content = report.to_yaml()
    path.write_text(content, encoding="utf-8")
    print(f"\nReport saved to {output}")

  return 0


def cmd_suites() -> int:
  """List available test suites in the suites/ directory."""
  suites_dir = Path("suites")
  if not suites_dir.is_dir():
    print("No suites/ directory found.")
    return 0

  suite_dirs = sorted(
    d for d in suites_dir.iterdir() if d.is_dir() and (d / "suite.yaml").is_file()
  )
  if not suite_dirs:
    print("No suites found in suites/ directory.")
    return 0

  print(f"{'Suite':<20} {'Version':<10} {'Tasks':>6}  Description")
  print("-" * 70)
  for d in suite_dirs:
    try:
      config = load_suite(d / "suite.yaml")
      print(f"{config.suite:<20} {config.version:<10} {len(config.tasks):>6}  {config.description}")
    except Exception as e:
      print(f"{d.name:<20} {'?':<10} {'?':>6}  Error: {e}")

  return 0


def cmd_show(suite: str) -> int:
  """Display the contents of a test suite without running it."""
  try:
    suite_path = _resolve_suite_path(suite)
    config = load_suite(suite_path)
  except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1

  errors = validate_suite(config)
  if errors:
    print("Validation errors:", file=sys.stderr)
    for err in errors:
      print(f"  - {err}", file=sys.stderr)
    return 1

  print(f"Suite:        {config.suite}")
  print(f"Version:      {config.version}")
  print(f"Description:  {config.description}")
  print(f"Repeats:      {config.repeats}")
  print(f"Temperature:  {config.temperature}")
  print(f"Seed:         {config.seed}")
  if config.max_tokens is not None:
    print(f"Max Tokens:   {config.max_tokens}")
  print()

  by_category: dict[str, list] = {}
  for task in config.tasks:
    by_category.setdefault(task.category, []).append(task)

  print("Tasks:")
  for cat in sorted(by_category.keys()):
    tasks = by_category[cat]
    print(f"\n  [{cat}] ({len(tasks)} tasks)")
    for task in tasks:
      difficulty = f" ({task.difficulty})" if task.difficulty else ""
      scorer = (
        task.scorer if isinstance(task.scorer, str) else getattr(task.scorer, "__name__", "custom")
      )
      print(f"    {task.id:<10} {scorer:<12}{difficulty}")

  if config.aggregation_weights:
    print("\nAggregation Weights:")
    for cat, weight in config.aggregation_weights.items():
      print(f"  {cat:<14} {weight:.2f}")

  return 0


def main() -> None:
  """CLI entry point with subcommand support."""
  parser = argparse.ArgumentParser(description="yoker-test: model evaluation through Yoker")
  parser.add_argument(
    "--model",
    default=None,
    help="Model to test (backward compat: runs yoker_basic suite)",
  )
  # --verbose for the legacy --model path; distinct dest avoids the argparse
  # wart where subparser defaults clobber the top-level namespace value.
  parser.add_argument(
    "--verbose",
    dest="legacy_verbose",
    action="store_true",
    help="Show full per-test detail (legacy --model path only)",
  )
  subparsers = parser.add_subparsers(dest="command")

  eval_parser = subparsers.add_parser("eval", help="Run an evaluation suite")
  eval_parser.add_argument("--suite", required=True, help="Suite name or path to suite file")
  eval_parser.add_argument("--model", default="glm-5.2:cloud", help="Model to evaluate")
  eval_parser.add_argument(
    "--compare", default=None, help="Baseline report file to compare against"
  )
  eval_parser.add_argument(
    "--output", default=None, help="Output file (YAML or JSON based on extension)"
  )
  eval_parser.add_argument(
    "--repeats", type=int, default=None, help="Override suite default repeats"
  )
  eval_parser.add_argument(
    "--with",
    dest="with_paths",
    action="append",
    default=[],
    help="Add a directory to sys.path before loading the suite (can be repeated)",
  )
  eval_parser.add_argument(
    "--verbose", action="store_true", help="Show full per-test detail (untruncated)"
  )

  subparsers.add_parser("suites", help="List available test suites")

  show_parser = subparsers.add_parser("show", help="Display suite contents without running")
  show_parser.add_argument("--suite", required=True, help="Suite name or path to suite file")

  args = parser.parse_args()

  if args.command == "eval":
    sys.exit(
      asyncio.run(
        cmd_eval(
          args.suite,
          args.model,
          args.compare,
          args.output,
          args.repeats,
          args.with_paths,
          args.verbose,
        )
      )
    )
  elif args.command == "suites":
    sys.exit(cmd_suites())
  elif args.command == "show":
    sys.exit(cmd_show(args.suite))
  elif args.model is not None:
    verbose = args.legacy_verbose
    sys.exit(asyncio.run(cmd_eval("yoker_basic", args.model, None, None, None, verbose=verbose)))
  else:
    parser.print_help()
    sys.exit(1)
