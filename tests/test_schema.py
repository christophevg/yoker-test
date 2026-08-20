"""Tests for yoker_test.schema."""

from yoker_test.schema import TestResult, TestTask


class TestTestTask:
  """Tests for TestTask dataclass."""

  def test_construction_with_required_fields(self):
    task = TestTask(
      id="K1",
      category="knowledge",
      prompt="What is 2+2?",
      expected="4",
      scorer="mcq",
    )
    assert task.id == "K1"
    assert task.category == "knowledge"
    assert task.prompt == "What is 2+2?"
    assert task.expected == "4"
    assert task.scorer == "mcq"

  def test_scorer_config_defaults_to_empty_dict(self):
    task = TestTask(id="K1", category="knowledge", prompt="?", expected="A", scorer="mcq")
    assert task.scorer_config == {}

  def test_scorer_config_accepts_custom_values(self):
    task = TestTask(
      id="K1",
      category="knowledge",
      prompt="?",
      expected="A",
      scorer="mcq",
      scorer_config={"case_sensitive": True},
    )
    assert task.scorer_config == {"case_sensitive": True}

  def test_scorer_config_is_independent_per_instance(self):
    """Each instance gets its own dict (not a shared mutable default)."""
    t1 = TestTask(id="A", category="c", prompt="?", expected="A", scorer="mcq")
    t2 = TestTask(id="B", category="c", prompt="?", expected="B", scorer="mcq")
    t1.scorer_config["key"] = "value"
    assert t2.scorer_config == {}


class TestTestResult:
  """Tests for TestResult dataclass."""

  def test_construction_with_required_fields(self):
    result = TestResult(
      task_id="K1",
      category="knowledge",
      score=1.0,
      response="C",
      extracted="C",
      tokens_in=10,
      tokens_out=5,
      latency_ms=42.0,
    )
    assert result.task_id == "K1"
    assert result.category == "knowledge"
    assert result.score == 1.0
    assert result.response == "C"
    assert result.extracted == "C"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.latency_ms == 42.0

  def test_optional_fields_default_to_zero(self):
    result = TestResult(
      task_id="K1",
      category="knowledge",
      score=0.0,
      response="",
      extracted=None,
      tokens_in=0,
      tokens_out=0,
      latency_ms=0.0,
    )
    assert result.thinking_chars == 0
    assert result.content_chars == 0

  def test_error_defaults_to_none(self):
    result = TestResult(
      task_id="K1",
      category="knowledge",
      score=0.0,
      response="",
      extracted=None,
      tokens_in=0,
      tokens_out=0,
      latency_ms=0.0,
    )
    assert result.error is None

  def test_error_can_be_set(self):
    result = TestResult(
      task_id="K1",
      category="knowledge",
      score=0.0,
      response="",
      extracted=None,
      tokens_in=0,
      tokens_out=0,
      latency_ms=0.0,
      error="Connection timeout",
    )
    assert result.error == "Connection timeout"

  def test_extracted_can_be_none(self):
    result = TestResult(
      task_id="K1",
      category="knowledge",
      score=0.0,
      response="I don't know",
      extracted=None,
      tokens_in=0,
      tokens_out=0,
      latency_ms=0.0,
    )
    assert result.extracted is None

  def test_field_types(self):
    """Verify field types are as declared."""
    import dataclasses

    fields = {f.name: f.type for f in dataclasses.fields(TestResult)}
    assert fields["score"] is float or fields["score"] == "float"
    assert fields["tokens_in"] is int or fields["tokens_in"] == "int"
    assert fields["latency_ms"] is float or fields["latency_ms"] == "float"
    # str | None resolves to the actual union type object on Python 3.10+
    assert fields["error"] == str | None or fields["error"] == "str | None"
