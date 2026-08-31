"""Config and public API for yoker-test evaluation runs."""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from yoker.config import Config, get_yoker_config

from yoker_test.loader import load_suite, validate_suite
from yoker_test.report import compare_baseline
from yoker_test.runner import EvalRunner
from yoker_test.schema import TestReport


@dataclass
class TestConfig(Config):
  """Configuration for yoker-test evaluation runs.

  Extends yoker's base Config with test-specific fields.
  """

  __test__ = False

  suite: str = ""
  model: str = "glm-5.2:cloud"
  compare: str | None = None
  output: str | None = None
  repeats: int | None = None


def _resolve_suite_path(suite: str) -> Path:
  """Resolve a suite name or path to a concrete file path.

  1. Direct path to an existing file → use it.
  2. Has a suffix (e.g., .yaml) → treat as path, error if not found.
  3. Otherwise, treat as suite name: suites/{name}/suite.yaml.
  """
  direct = Path(suite)
  if direct.is_file():
    return direct.resolve()

  if Path(suite).suffix:
    raise FileNotFoundError(f"Suite file not found: {suite}")

  suite_path = Path("suites") / suite / "suite.yaml"
  if suite_path.is_file():
    return suite_path.resolve()

  raise FileNotFoundError(
    f"Suite not found: {suite!r}. Looked for: {suite_path} (tried direct path and suite name)"
  )


def _load_baseline(path: str) -> TestReport:
  """Load a serialized TestReport from a YAML or JSON file."""
  file_path = Path(path)
  content = file_path.read_text(encoding="utf-8")

  if file_path.suffix == ".json":
    data = json.loads(content)
  else:
    data = yaml.safe_load(content)

  return TestReport.from_dict(data)


async def evaluate(
  suite: str,
  model: str,
  compare: str | None = None,
  *,
  config: Config | None = None,
  repeats: int | None = None,
  verbose: bool = False,
) -> TestReport:
  """Run an evaluation suite and return a TestReport.

  Loads and validates the suite, creates an EvalRunner, executes it
  through Yoker, and optionally compares against a baseline report.
  With verbose=True, the runner streams a detail block per test to stderr.

  Note: mutates ``config.backend.config.model`` in place.
  """
  suite_path = _resolve_suite_path(suite)
  suite_config = load_suite(suite_path)

  errors = validate_suite(suite_config)
  if errors:
    raise ValueError(f"Suite validation failed: {'; '.join(errors)}")

  if config is None:
    config = get_yoker_config()

  config.backend.config.model = model
  config.backend.validate()

  effective_repeats = repeats if repeats is not None else suite_config.repeats

  runner = EvalRunner(
    tasks=suite_config.tasks,
    repeats=effective_repeats,
    temperature=suite_config.temperature,
    seed=suite_config.seed,
    suite_name=suite_config.suite,
    suite_version=suite_config.version,
    aggregation_weights=suite_config.aggregation_weights,
  )
  report = await runner.run(model, config, verbose=verbose)

  if compare is not None:
    baseline = _load_baseline(compare)
    report.comparison = compare_baseline(report, baseline)

  return report
