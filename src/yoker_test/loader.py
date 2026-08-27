"""Suite loader: parse YAML suite files into SuiteConfig objects."""

import importlib
import sys
from collections.abc import Callable
from pathlib import Path

import yaml

from yoker_test.schema import SuiteConfig, TestTask
from yoker_test.scorers import SCORERS


def _resolve_function(dotted_path: str) -> Callable:
  """Resolve 'module.path.attribute' to a callable via importlib + getattr."""
  parts = dotted_path.rsplit(".", 1)
  if len(parts) < 2:
    raise ValueError(f"!function expects 'module.path.function' notation, got: {dotted_path!r}")

  module_path, attr_name = parts
  try:
    module = importlib.import_module(module_path)
  except ImportError as e:
    raise ValueError(f"!function could not import module {module_path!r}: {e}") from e

  try:
    func: Callable = getattr(module, attr_name)
  except AttributeError as e:
    raise ValueError(f"!function: module {module_path!r} has no attribute {attr_name!r}") from e

  return func


def _function_constructor(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> Callable:
  """YAML constructor for !function tags."""
  dotted_path = loader.construct_scalar(node)
  return _resolve_function(dotted_path)


class SuiteLoader(yaml.SafeLoader):
  """SafeLoader subclass with !function tag support."""


SuiteLoader.add_constructor("!function", _function_constructor)


def _build_task(task_dict: dict, scorer_config_defaults: dict) -> TestTask:
  """Construct a TestTask from a YAML dict, merging scorer config defaults."""
  scorer = task_dict["scorer"]

  # Merge suite-level scorer defaults with task-level config (task wins)
  config = dict(scorer_config_defaults.get(scorer if isinstance(scorer, str) else "", {}))
  config.update(task_dict.get("scorer_config", {}))

  return TestTask(
    id=task_dict["id"],
    category=task_dict["category"],
    prompt=task_dict["prompt"],
    expected=task_dict["expected"],
    scorer=scorer,
    difficulty=task_dict.get("difficulty", ""),
    system_prompt=task_dict.get("system_prompt"),
    scorer_config=config,
  )


def load_suite(path: str | Path) -> SuiteConfig:
  """Load a YAML suite file into a SuiteConfig.

  Raises FileNotFoundError if the file doesn't exist, yaml.YAMLError for
  malformed YAML, ValueError for unresolvable !function tags, and KeyError
  for missing required suite-level fields.
  """
  resolved = Path(path).resolve()
  if not resolved.exists():
    raise FileNotFoundError(f"Suite file not found: {resolved}")

  # Auto-include the suite's directory for !function resolution
  suite_dir = str(resolved.parent)
  if suite_dir not in sys.path:
    sys.path.insert(0, suite_dir)

  with open(resolved, encoding="utf-8") as f:
    raw = yaml.load(f, Loader=SuiteLoader)

  suite = raw["suite"]
  version = raw["version"]
  description = raw["description"]

  repeats = raw.get("repeats", 3)
  temperature = raw.get("temperature", 0.0)
  seed = raw.get("seed", 42)
  max_tokens = raw.get("max_tokens")

  # Aggregation weights nested under "aggregation.weights"
  aggregation = raw.get("aggregation") or {}
  aggregation_weights = aggregation.get("weights")

  # Per-suite scorer config defaults (keyed by scorer name)
  scorer_config_defaults = raw.get("scorers") or {}

  # Resolve tasks: static tasks always loaded, generator output appended
  task_generator = raw.get("task_generator")
  generator_config = raw.get("generator_config")

  raw_tasks = raw.get("tasks") or []
  tasks = [_build_task(t, scorer_config_defaults) for t in raw_tasks]

  if task_generator is not None:
    config = generator_config or {}
    generated = task_generator(config)
    if not isinstance(generated, list):
      raise ValueError(f"task_generator returned {type(generated).__name__}, expected list")
    for item in generated:
      if isinstance(item, TestTask):
        tasks.append(item)
      elif isinstance(item, dict):
        tasks.append(_build_task(item, scorer_config_defaults))
      else:
        raise ValueError(
          f"task_generator returned {type(item).__name__}, expected TestTask or dict"
        )

  return SuiteConfig(
    suite=suite,
    version=version,
    description=description,
    repeats=repeats,
    temperature=temperature,
    seed=seed,
    max_tokens=max_tokens,
    tasks=tasks,
    task_generator=task_generator,
    generator_config=generator_config,
    aggregation_weights=aggregation_weights,
  )


def validate_suite(config: SuiteConfig) -> list[str]:
  """Validate a SuiteConfig, returning a list of error strings (empty = valid)."""
  errors: list[str] = []

  if not config.suite:
    errors.append("Suite field 'suite' is required and must not be empty")
  if not config.version:
    errors.append("Suite field 'version' is required and must not be empty")
  if not config.description:
    errors.append("Suite field 'description' is required and must not be empty")

  if not config.tasks:
    errors.append("Suite has no tasks (neither static tasks nor task_generator output)")

  seen_ids: set[str] = set()
  for task in config.tasks:
    if task.id in seen_ids:
      errors.append(f"Duplicate task ID: {task.id!r}")
    seen_ids.add(task.id)

    if not task.id:
      errors.append("Task missing required field: id")
    if not task.category:
      errors.append(f"Task {task.id!r} missing required field: category")
    if not task.prompt:
      errors.append(f"Task {task.id!r} missing required field: prompt")
    if not task.scorer:
      errors.append(f"Task {task.id!r} missing required field: scorer")

    if isinstance(task.scorer, str):
      if task.scorer not in SCORERS:
        errors.append(
          f"Task {task.id!r} references unknown scorer: {task.scorer!r}. "
          f"Available: {', '.join(sorted(SCORERS.keys()))}"
        )
    elif not callable(task.scorer):
      errors.append(
        f"Task {task.id!r} scorer must be a string name or callable, "
        f"got: {type(task.scorer).__name__}"
      )

  return errors
