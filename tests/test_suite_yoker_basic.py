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
    assert len(config.tasks) >= 1

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
