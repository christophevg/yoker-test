"""Tests for the real yoker_basic suite file."""

from pathlib import Path

from yoker_test.loader import load_suite, validate_suite

SUITE_PATH = Path(__file__).parent.parent / "suites" / "yoker_basic" / "suite.yaml"


class TestYokerBasicSuite:
  """Tests loading and validating the real yoker_basic suite.yaml."""

  def test_loads_successfully(self):
    """Suite file loads with expected metadata."""
    config = load_suite(SUITE_PATH)
    assert config.suite == "yoker_basic"
    assert config.version == "1.0"
    assert config.description == "Basic evaluation suite with 30 tasks across 5 categories"
    assert config.repeats == 3
    assert config.temperature == 0.0
    assert config.seed == 42
    assert config.max_tokens == 4096

  def test_validates_without_errors(self):
    """Suite passes validation with no errors."""
    config = load_suite(SUITE_PATH)
    errors = validate_suite(config)
    assert errors == []

  def test_contains_original_mcq_task(self):
    """Suite contains the original K1 gold-symbol MCQ task."""
    config = load_suite(SUITE_PATH)
    task = next(t for t in config.tasks if t.id == "K1")
    assert task.category == "knowledge"
    assert task.expected == "C"
    assert task.scorer == "mcq"

  def test_total_task_count(self):
    """Suite has 30 tasks (28 static + 2 dynamic)."""
    config = load_suite(SUITE_PATH)
    assert len(config.tasks) == 30

  def test_category_distribution(self):
    """Tasks are distributed across 5 categories: 8/8/6/4/4."""
    config = load_suite(SUITE_PATH)
    by_category: dict[str, int] = {}
    for task in config.tasks:
      by_category[task.category] = by_category.get(task.category, 0) + 1
    assert by_category.get("knowledge") == 8
    assert by_category.get("reasoning") == 8
    assert by_category.get("instruction") == 6
    assert by_category.get("code") == 4
    assert by_category.get("tool_use") == 4

  def test_aggregation_weights(self):
    """Suite has correct aggregation weights."""
    config = load_suite(SUITE_PATH)
    assert config.aggregation_weights == {
      "knowledge": 0.25,
      "reasoning": 0.25,
      "instruction": 0.20,
      "code": 0.15,
      "tool_use": 0.15,
    }

  def test_dynamic_tasks_present(self):
    """Suite has 2 dynamic tasks from the generator."""
    config = load_suite(SUITE_PATH)
    dynamic = [t for t in config.tasks if t.id.startswith("R_DYN_")]
    assert len(dynamic) == 2

  def test_custom_scorers_resolved(self):
    """Instruction tasks use !function scorers (callables)."""
    config = load_suite(SUITE_PATH)
    instruction_tasks = [t for t in config.tasks if t.category == "instruction"]
    assert len(instruction_tasks) == 6
    for task in instruction_tasks:
      assert callable(task.scorer)

  def test_tool_use_scorers_resolved(self):
    """Tool-use tasks use !function scorers (callables)."""
    config = load_suite(SUITE_PATH)
    tool_tasks = [t for t in config.tasks if t.category == "tool_use"]
    assert len(tool_tasks) == 4
    for task in tool_tasks:
      assert callable(task.scorer)

  def test_no_duplicate_ids(self):
    """All task IDs are unique."""
    config = load_suite(SUITE_PATH)
    ids = [t.id for t in config.tasks]
    assert len(ids) == len(set(ids))
