"""Tests for yoker_test.schema."""

import json

import yaml

from yoker_test.schema import (
  CategorySummary,
  ComparisonReport,
  OverallSummary,
  RunMetadata,
  Score,
  SuiteConfig,
  TestReport,
  TestResult,
  TestTask,
)


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

  def test_difficulty_defaults_to_empty_string(self):
    task = TestTask(id="K1", category="c", prompt="?", expected="A", scorer="mcq")
    assert task.difficulty == ""

  def test_system_prompt_defaults_to_none(self):
    task = TestTask(id="K1", category="c", prompt="?", expected="A", scorer="mcq")
    assert task.system_prompt is None

  def test_expected_accepts_any_type(self):
    """expected is typed as Any — non-string values work."""
    task = TestTask(id="K1", category="c", prompt="?", expected=42, scorer="mcq")
    assert task.expected == 42

  def test_scorer_accepts_callable(self):
    """scorer is typed as str | Callable."""

    def custom_scorer(task, response):
      return (1.0, "yes")

    task = TestTask(id="K1", category="c", prompt="?", expected="A", scorer=custom_scorer)
    assert callable(task.scorer)
    assert task.scorer is custom_scorer


class TestScore:
  """Tests for Score dataclass."""

  def test_construction_with_value_only(self):
    score = Score(value=1.0)
    assert score.value == 1.0
    assert score.extracted is None
    assert score.sub_scores is None
    assert score.explanation is None

  def test_construction_with_all_fields(self):
    score = Score(
      value=0.5,
      extracted="B",
      sub_scores={"strict": 0.0, "flexible": 1.0},
      explanation="Flexible match found",
    )
    assert score.value == 0.5
    assert score.extracted == "B"
    assert score.sub_scores == {"strict": 0.0, "flexible": 1.0}
    assert score.explanation == "Flexible match found"


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
    )
    assert result.thinking_chars == 0
    assert result.content_chars == 0
    assert result.latency_ms == 0.0

  def test_error_defaults_to_none(self):
    result = TestResult(task_id="K1", category="knowledge", score=0.0, response="")
    assert result.error is None

  def test_error_can_be_set(self):
    result = TestResult(
      task_id="K1", category="knowledge", score=0.0, response="", error="Connection timeout"
    )
    assert result.error == "Connection timeout"

  def test_expected_defaults_to_none(self):
    result = TestResult(task_id="K1", category="knowledge", score=0.0, response="")
    assert result.expected is None

  def test_extracted_can_be_none(self):
    result = TestResult(
      task_id="K1", category="knowledge", score=0.0, response="I don't know", extracted=None
    )
    assert result.extracted is None

  def test_tokens_in_can_be_none(self):
    """tokens_in is now nullable (int | None)."""
    result = TestResult(task_id="K1", category="knowledge", score=0.0, response="", tokens_in=None)
    assert result.tokens_in is None

  def test_tokens_out_can_be_none(self):
    """tokens_out is now nullable (int | None)."""
    result = TestResult(task_id="K1", category="knowledge", score=0.0, response="", tokens_out=None)
    assert result.tokens_out is None

  def test_new_fields_default_correctly(self):
    result = TestResult(task_id="K1", category="knowledge", score=0.0, response="")
    assert result.difficulty == ""
    assert result.repeat == 0
    assert result.prompt == ""
    assert result.messages == []
    assert result.ttft_ms is None
    assert result.scorer_name == ""
    assert result.sub_scores is None

  def test_messages_are_independent_per_instance(self):
    """Each instance gets its own list (not a shared mutable default)."""
    r1 = TestResult(task_id="A", category="c", score=0.0, response="")
    r2 = TestResult(task_id="B", category="c", score=0.0, response="")
    r1.messages.append({"role": "user", "content": "hi"})
    assert r2.messages == []


class TestRunMetadata:
  """Tests for RunMetadata dataclass."""

  def test_construction_with_required_fields(self):
    meta = RunMetadata(
      suite="yoker_basic",
      suite_version="1.0",
      model="glm-5.2:cloud",
      provider="ollama",
      yoker_version="0.10.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-15T12:00:00Z",
    )
    assert meta.suite == "yoker_basic"
    assert meta.model == "glm-5.2:cloud"
    assert meta.repeats == 3


class TestSuiteConfig:
  """Tests for SuiteConfig dataclass."""

  def test_construction_with_required_fields(self):
    config = SuiteConfig(suite="yoker_basic", version="1.0", description="Basic suite")
    assert config.suite == "yoker_basic"
    assert config.version == "1.0"
    assert config.description == "Basic suite"

  def test_defaults(self):
    config = SuiteConfig(suite="s", version="1", description="d")
    assert config.repeats == 3
    assert config.temperature == 0.0
    assert config.seed == 42
    assert config.max_tokens is None
    assert config.tasks == []
    assert config.task_generator is None
    assert config.generator_config is None
    assert config.aggregation_weights is None

  def test_tasks_are_independent_per_instance(self):
    c1 = SuiteConfig(suite="s", version="1", description="d")
    c2 = SuiteConfig(suite="s", version="1", description="d")
    c1.tasks.append(TestTask(id="T1", category="c", prompt="?", expected="A", scorer="mcq"))
    assert c2.tasks == []


class TestCategorySummary:
  """Tests for CategorySummary dataclass."""

  def test_construction_with_required_fields(self):
    summary = CategorySummary(
      score=0.85,
      std=0.1,
      n_tasks=10,
      avg_tokens_in=50.0,
      avg_tokens_out=100.0,
      avg_latency_ms=500.0,
      total_tokens=1500,
      total_latency_s=5.0,
    )
    assert summary.score == 0.85
    assert summary.n_tasks == 10
    assert summary.total_tokens == 1500


class TestOverallSummary:
  """Tests for OverallSummary dataclass."""

  def test_construction_with_required_fields(self):
    summary = OverallSummary(
      score=0.85,
      std=0.1,
      total_tokens_in=500,
      total_tokens_out=1000,
      total_tokens=1500,
      total_latency_s=5.0,
      avg_tokens_per_second=300.0,
    )
    assert summary.score == 0.85
    assert summary.total_tokens == 1500
    assert summary.usage_delta is None

  def test_usage_delta_can_be_set(self):
    summary = OverallSummary(
      score=0.8,
      std=0.1,
      total_tokens_in=0,
      total_tokens_out=0,
      total_tokens=0,
      total_latency_s=0.0,
      avg_tokens_per_second=0.0,
      usage_delta={"session": 0.02, "weekly": 0.05},
    )
    assert summary.usage_delta == {"session": 0.02, "weekly": 0.05}


class TestUsageFields:
  """Tests for P2.5.10 usage fields on TestResult and OverallSummary."""

  def make_report(self, with_usage: bool = True) -> TestReport:
    run = RunMetadata(
      suite="s",
      suite_version="1",
      model="glm-5.2:cloud",
      provider="ollama",
      yoker_version="0.10.1",
      temperature=0.0,
      seed=42,
      repeats=1,
      timestamp="2025-01-01",
    )
    kwargs = (
      {"usage_delta": {"session": 0.004, "weekly": 0.001}, "requests_delta": 1}
      if with_usage
      else {}
    )
    results = [
      TestResult(task_id="K1", category="knowledge", score=1.0, response="C", **kwargs)
      for _ in range(2)
    ]
    overall_kwargs = (
      {
        "usage_delta": {"session": 0.008, "weekly": 0.002},
        "usage_note": None,
        "usage_before": {"session": 0.046, "weekly": 0.051},
        "usage_after": {"session": 0.054, "weekly": 0.053},
        "requests_delta": 2,
        "extra_usage_cost_delta": 0.5,
        "composite": 0.99,
      }
      if with_usage
      else {}
    )
    overall = OverallSummary(
      score=1.0,
      std=0.0,
      total_tokens_in=0,
      total_tokens_out=0,
      total_tokens=0,
      total_latency_s=0.0,
      avg_tokens_per_second=0.0,
      **overall_kwargs,
    )
    return TestReport(run=run, results=results, summary={}, overall=overall)

  def test_new_fields_default_to_none(self):
    result = TestResult(task_id="K1", category="k", score=1.0, response="")
    assert result.usage_delta is None
    assert result.requests_delta is None
    overall = OverallSummary(
      score=0.0,
      std=0.0,
      total_tokens_in=0,
      total_tokens_out=0,
      total_tokens=0,
      total_latency_s=0.0,
      avg_tokens_per_second=0.0,
    )
    assert overall.usage_note is None
    assert overall.usage_before is None
    assert overall.usage_after is None
    assert overall.requests_delta is None
    assert overall.extra_usage_cost_delta is None
    assert overall.composite is None

  def test_round_trip_preserves_usage_fields(self):
    report = self.make_report()
    d = report.to_dict()
    assert d["results"][0]["usage_delta"] == {"session": 0.004, "weekly": 0.001}
    assert d["results"][0]["requests_delta"] == 1
    assert d["overall"]["composite"] == 0.99
    assert d["overall"]["extra_usage_cost_delta"] == 0.5
    report.to_yaml()
    report.to_json()  # all values JSON-serializable
    loaded = TestReport.from_dict(d)
    assert loaded.results[0].usage_delta == {"session": 0.004, "weekly": 0.001}
    assert loaded.results[0].requests_delta == 1
    assert loaded.overall.usage_before == {"session": 0.046, "weekly": 0.051}
    assert loaded.overall.usage_after == {"session": 0.054, "weekly": 0.053}
    assert loaded.overall.requests_delta == 2
    assert loaded.overall.extra_usage_cost_delta == 0.5
    assert loaded.overall.composite == 0.99

  def test_old_file_without_new_keys_loads_with_defaults(self):
    report = self.make_report(with_usage=False)
    loaded = TestReport.from_dict(report.to_dict())
    assert loaded.results[0].usage_delta is None
    assert loaded.results[0].requests_delta is None
    assert loaded.overall.usage_note is None
    assert loaded.overall.usage_before is None
    assert loaded.overall.usage_after is None
    assert loaded.overall.requests_delta is None
    assert loaded.overall.extra_usage_cost_delta is None
    assert loaded.overall.composite is None

  def test_serialization_carries_normalized_fields_only(self):
    """Security invariant: no raw-payload fields (e.g. limits.*, activity.*) leak out."""
    report = self.make_report()
    raw_payload_keys = {"limits", "activity", "models", "request_count", "api_key", "cost_raw"}
    d = report.to_dict()

    def walk(node):
      if isinstance(node, dict):
        assert not raw_payload_keys & set(node.keys())
        for v in node.values():
          walk(v)
      elif isinstance(node, list):
        for v in node:
          walk(v)

    walk(d)


class TestComparisonReport:
  """Tests for ComparisonReport dataclass."""

  def test_construction_with_required_fields(self):
    baseline = RunMetadata(
      suite="s",
      suite_version="1",
      model="m",
      provider="p",
      yoker_version="0.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-01",
    )
    report = ComparisonReport(baseline=baseline, delta={"score": -0.05})
    assert report.baseline.model == "m"
    assert report.delta == {"score": -0.05}
    assert report.flagged == []

  def test_flagged_can_be_set(self):
    baseline = RunMetadata(
      suite="s",
      suite_version="1",
      model="m",
      provider="p",
      yoker_version="0.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-01",
    )
    report = ComparisonReport(baseline=baseline, delta={"score": -0.05}, flagged=["score"])
    assert report.flagged == ["score"]


class TestTestReport:
  """Tests for TestReport dataclass."""

  def _make_report(self) -> TestReport:
    """Create a minimal TestReport for testing."""
    run = RunMetadata(
      suite="yoker_basic",
      suite_version="1.0",
      model="glm-5.2:cloud",
      provider="ollama",
      yoker_version="0.10.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-15T12:00:00Z",
    )
    results = [
      TestResult(
        task_id="K1",
        category="knowledge",
        score=1.0,
        response="C",
        extracted="C",
        tokens_in=10,
        tokens_out=5,
        latency_ms=42.0,
      )
    ]
    summary = {
      "knowledge": CategorySummary(
        score=1.0,
        std=0.0,
        n_tasks=1,
        avg_tokens_in=10.0,
        avg_tokens_out=5.0,
        avg_latency_ms=42.0,
        total_tokens=15,
        total_latency_s=0.042,
      )
    }
    overall = OverallSummary(
      score=1.0,
      std=0.0,
      total_tokens_in=10,
      total_tokens_out=5,
      total_tokens=15,
      total_latency_s=0.042,
      avg_tokens_per_second=357.14,
      usage_delta={"session": 0.001, "weekly": 0.002},
    )
    return TestReport(run=run, results=results, summary=summary, overall=overall)

  def test_construction_with_required_fields(self):
    run = RunMetadata(
      suite="s",
      suite_version="1",
      model="m",
      provider="p",
      yoker_version="0.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-01",
    )
    report = TestReport(run=run)
    assert report.run.model == "m"
    assert report.results == []
    assert report.summary == {}
    assert report.overall is None
    assert report.comparison is None

  def test_to_dict_produces_correct_structure(self):
    report = self._make_report()
    d = report.to_dict()
    assert d["run"]["model"] == "glm-5.2:cloud"
    assert d["run"]["suite"] == "yoker_basic"
    assert len(d["results"]) == 1
    assert d["results"][0]["task_id"] == "K1"
    assert d["results"][0]["score"] == 1.0
    assert "knowledge" in d["summary"]
    assert d["summary"]["knowledge"]["score"] == 1.0
    assert d["overall"]["total_tokens"] == 15
    assert d["overall"]["usage_delta"] == {"session": 0.001, "weekly": 0.002}

  def test_to_json_produces_valid_json(self):
    report = self._make_report()
    s = report.to_json()
    d = json.loads(s)
    assert d["run"]["model"] == "glm-5.2:cloud"
    assert d["results"][0]["task_id"] == "K1"
    assert d["overall"]["total_tokens"] == 15

  def test_to_yaml_produces_valid_yaml(self):
    report = self._make_report()
    s = report.to_yaml()
    d = yaml.safe_load(s)
    assert d["run"]["model"] == "glm-5.2:cloud"
    assert d["results"][0]["task_id"] == "K1"
    assert d["overall"]["total_tokens"] == 15

  def test_to_dict_with_comparison(self):
    run = RunMetadata(
      suite="s",
      suite_version="1",
      model="m",
      provider="p",
      yoker_version="0.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-01",
    )
    report = TestReport(
      run=run,
      comparison=ComparisonReport(baseline=run, delta={"score": -0.1}, flagged=["score"]),
    )
    d = report.to_dict()
    assert d["comparison"]["delta"] == {"score": -0.1}
    assert d["comparison"]["flagged"] == ["score"]
