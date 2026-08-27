"""Tests for yoker_test.loader."""

import math
from pathlib import Path

import pytest
import yaml

from yoker_test.loader import load_suite, validate_suite
from yoker_test.schema import SuiteConfig, TestTask


def write_suite(tmp_path: Path, content: str) -> Path:
  """Write YAML content to a temp file and return its path."""
  p = tmp_path / "suite.yaml"
  p.write_text(content)
  return p


VALID_STATIC_SUITE = """
suite: test_basic
version: "1.0"
description: "A basic test suite"
repeats: 5
temperature: 0.1
seed: 99
max_tokens: 2048
tasks:
  - id: K1
    category: knowledge
    difficulty: easy
    prompt: "What is the capital of France?"
    expected: "C"
    scorer: mcq
  - id: R1
    category: reasoning
    prompt: "If A>B and B>C, then A>?"
    expected: "C"
    scorer: mcq
  - id: E1
    category: exact
    prompt: "Say hello"
    expected: "hello"
    scorer: exact_match
    scorer_config:
      ignore_case: true
aggregation:
  weights:
    knowledge: 0.4
    reasoning: 0.3
    exact: 0.3
"""


class TestLoadSuite:
  """Tests for load_suite()."""

  def test_valid_static_suite(self, tmp_path):
    """Load a well-formed YAML suite with 3 static tasks."""
    path = write_suite(tmp_path, VALID_STATIC_SUITE)
    config = load_suite(path)

    assert config.suite == "test_basic"
    assert config.version == "1.0"
    assert config.description == "A basic test suite"
    assert config.repeats == 5
    assert config.temperature == 0.1
    assert config.seed == 99
    assert config.max_tokens == 2048
    assert len(config.tasks) == 3

    assert config.tasks[0].id == "K1"
    assert config.tasks[0].category == "knowledge"
    assert config.tasks[0].difficulty == "easy"
    assert config.tasks[0].scorer == "mcq"

    assert config.tasks[2].scorer_config == {"ignore_case": True}

  def test_function_scorer_resolution(self, tmp_path):
    """!function tag resolves to a callable stored in TestTask.scorer."""
    yaml_content = """
suite: func_test
version: "1.0"
description: "Suite with !function scorer"
tasks:
  - id: T1
    category: math
    prompt: "What is sqrt(4)?"
    expected: 2.0
    scorer: !function math.sqrt
"""
    path = write_suite(tmp_path, yaml_content)
    config = load_suite(path)

    assert config.tasks[0].scorer is math.sqrt

  def test_task_generator_expansion(self, tmp_path):
    """task_generator is called with generator_config to produce tasks."""
    yaml_content = """
suite: gen_test
version: "1.0"
description: "Suite with task generator"
task_generator: !function tests.test_loader._sample_generator
generator_config:
  count: 3
  prefix: G
"""
    path = write_suite(tmp_path, yaml_content)
    config = load_suite(path)

    assert len(config.tasks) == 3
    assert config.tasks[0].id == "G0"
    assert config.tasks[1].id == "G1"
    assert config.tasks[2].id == "G2"

  def test_function_unresolvable_module(self, tmp_path):
    """!function with a non-existent module raises ValueError."""
    yaml_content = """
suite: err_test
version: "1.0"
description: "Bad module"
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "A"
    scorer: !function nonexistent_module_xyz.func
"""
    path = write_suite(tmp_path, yaml_content)
    with pytest.raises(ValueError, match="could not import module"):
      load_suite(path)

  def test_function_unresolvable_attribute(self, tmp_path):
    """!function with a missing attribute raises ValueError."""
    yaml_content = """
suite: err_test
version: "1.0"
description: "Bad attribute"
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "A"
    scorer: !function math.nonexistent_function_xyz
"""
    path = write_suite(tmp_path, yaml_content)
    with pytest.raises(ValueError, match="no attribute"):
      load_suite(path)

  def test_function_missing_dot(self, tmp_path):
    """!function without a dot separator raises ValueError."""
    yaml_content = """
suite: err_test
version: "1.0"
description: "No dot"
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "A"
    scorer: !function nodotpath
"""
    path = write_suite(tmp_path, yaml_content)
    with pytest.raises(ValueError, match="expects 'module.path"):
      load_suite(path)

  def test_missing_file_raises_filenotfound(self, tmp_path):
    """Loading a non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
      load_suite(tmp_path / "nonexistent.yaml")

  def test_malformed_yaml_raises_yamlerror(self, tmp_path):
    """Malformed YAML raises yaml.YAMLError."""
    path = write_suite(tmp_path, "suite: [unclosed\n  - bad: yaml: [")
    with pytest.raises(yaml.YAMLError):
      load_suite(path)

  def test_missing_required_suite_field_raises_keyerror(self, tmp_path):
    """Missing 'description' raises KeyError."""
    yaml_content = """
suite: incomplete
version: "1.0"
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "A"
    scorer: mcq
"""
    path = write_suite(tmp_path, yaml_content)
    with pytest.raises(KeyError):
      load_suite(path)

  def test_scorer_config_merge(self, tmp_path):
    """Suite-level scorer defaults merge with task-level config (task wins)."""
    yaml_content = """
suite: merge_test
version: "1.0"
description: "Scorer config merge"
scorers:
  exact_match:
    ignore_case: true
    ignore_punctuation: false
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "hello"
    scorer: exact_match
    scorer_config:
      ignore_punctuation: true
"""
    path = write_suite(tmp_path, yaml_content)
    config = load_suite(path)

    # Suite default + task override merged, task wins on conflict
    assert config.tasks[0].scorer_config == {
      "ignore_case": True,
      "ignore_punctuation": True,
    }

  def test_both_tasks_and_generator_merged(self, tmp_path):
    """When both tasks and task_generator are present, they are merged."""
    yaml_content = """
suite: both_test
version: "1.0"
description: "Both present"
tasks:
  - id: STATIC1
    category: c
    prompt: "?"
    expected: "A"
    scorer: mcq
task_generator: !function tests.test_loader._sample_generator
generator_config:
  count: 2
  prefix: DYN
"""
    path = write_suite(tmp_path, yaml_content)
    config = load_suite(path)

    # Static + dynamic tasks are merged (static first, then generated)
    assert len(config.tasks) == 3
    assert config.tasks[0].id == "STATIC1"
    assert config.tasks[1].id == "DYN0"
    assert config.tasks[2].id == "DYN1"

  def test_empty_generator_config(self, tmp_path):
    """Generator is called with {} when generator_config is absent."""
    yaml_content = """
suite: empty_config_test
version: "1.0"
description: "No generator_config"
task_generator: !function tests.test_loader._generator_no_config
"""
    path = write_suite(tmp_path, yaml_content)
    config = load_suite(path)

    assert len(config.tasks) == 1
    assert config.tasks[0].id == "DEFAULT"

  def test_aggregation_weights_mapped(self, tmp_path):
    """aggregation.weights is correctly mapped to aggregation_weights."""
    path = write_suite(tmp_path, VALID_STATIC_SUITE)
    config = load_suite(path)

    assert config.aggregation_weights == {
      "knowledge": 0.4,
      "reasoning": 0.3,
      "exact": 0.3,
    }

  def test_generator_returns_non_list(self, tmp_path):
    """Generator returning a non-list raises ValueError."""
    yaml_content = """
suite: non_list_test
version: "1.0"
description: "Generator returns non-list"
task_generator: !function tests.test_loader._generator_returns_non_list
"""
    path = write_suite(tmp_path, yaml_content)
    with pytest.raises(ValueError, match="expected list"):
      load_suite(path)

  def test_generator_returns_invalid_item_type(self, tmp_path):
    """Generator returning an invalid item type raises ValueError."""
    yaml_content = """
suite: invalid_item_test
version: "1.0"
description: "Generator returns invalid item"
task_generator: !function tests.test_loader._generator_returns_invalid_item
"""
    path = write_suite(tmp_path, yaml_content)
    with pytest.raises(ValueError, match="expected TestTask or dict"):
      load_suite(path)


class TestValidateSuite:
  """Tests for validate_suite()."""

  def test_valid_suite_returns_empty_list(self, tmp_path):
    """A valid suite produces no validation errors."""
    path = write_suite(tmp_path, VALID_STATIC_SUITE)
    config = load_suite(path)
    errors = validate_suite(config)
    assert errors == []

  def test_duplicate_task_ids(self):
    """Duplicate task IDs produce validation errors."""
    config = SuiteConfig(
      suite="dup_test",
      version="1.0",
      description="Duplicates",
      tasks=[
        TestTask(id="K1", category="c", prompt="?", expected="A", scorer="mcq"),
        TestTask(id="K1", category="c", prompt="?", expected="B", scorer="mcq"),
      ],
    )
    errors = validate_suite(config)
    assert any("Duplicate task ID" in e for e in errors)

  def test_unknown_scorer_name(self):
    """Unknown scorer name produces validation error."""
    config = SuiteConfig(
      suite="bad_scorer",
      version="1.0",
      description="Bad scorer",
      tasks=[
        TestTask(id="T1", category="c", prompt="?", expected="A", scorer="nonexistent"),
      ],
    )
    errors = validate_suite(config)
    assert any("unknown scorer" in e for e in errors)

  def test_scorer_neither_str_nor_callable(self):
    """Scorer that's neither a string nor callable produces validation error."""
    config = SuiteConfig(
      suite="bad_type",
      version="1.0",
      description="Bad scorer type",
      tasks=[
        TestTask(id="T1", category="c", prompt="?", expected="A", scorer=42),
      ],
    )
    errors = validate_suite(config)
    assert any("must be a string name or callable" in e for e in errors)

  def test_empty_suite_field_validation(self):
    """Empty suite/version/description strings produce validation errors."""
    config = SuiteConfig(
      suite="",
      version="",
      description="",
      tasks=[
        TestTask(id="T1", category="c", prompt="?", expected="A", scorer="mcq"),
      ],
    )
    errors = validate_suite(config)
    assert any("'suite'" in e for e in errors)
    assert any("'version'" in e for e in errors)
    assert any("'description'" in e for e in errors)


# --- Helper functions for task_generator tests ---


def _sample_generator(config: dict) -> list[TestTask]:
  """Generate tasks based on count and prefix from config."""
  count = config.get("count", 0)
  prefix = config.get("prefix", "G")
  return [
    TestTask(
      id=f"{prefix}{i}",
      category="generated",
      prompt=f"Question {i}",
      expected="A",
      scorer="mcq",
    )
    for i in range(count)
  ]


def _generator_no_config(config: dict) -> list[TestTask]:
  """Generator that returns a single default task, verifying config is {}."""
  assert config == {}
  return [
    TestTask(
      id="DEFAULT",
      category="gen",
      prompt="default",
      expected="A",
      scorer="mcq",
    )
  ]


def _generator_returns_non_list(config: dict) -> int:
  """Generator that returns a non-list value."""
  return 42


def _generator_returns_invalid_item(config: dict) -> list:
  """Generator that returns a list with an invalid item type."""
  return ["not_a_test_task"]
