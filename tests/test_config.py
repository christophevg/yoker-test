"""Tests for yoker_test.config and public API exports."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from yoker.config import Config

from yoker_test.config import TestConfig, _load_baseline, _resolve_suite_path, evaluate
from yoker_test.schema import (
  CategorySummary,
  ComparisonReport,
  OverallSummary,
  RunMetadata,
  TestReport,
  TestResult,
)


class TestTestConfig:
  """Tests for TestConfig dataclass."""

  def test_extends_yoker_config(self):
    """TestConfig is a subclass of yoker.Config."""
    tc = TestConfig()
    assert isinstance(tc, Config)

  def test_default_values(self):
    tc = TestConfig()
    assert tc.suite == ""
    assert tc.model == "glm-5.2:cloud"
    assert tc.compare is None
    assert tc.output is None
    assert tc.repeats is None

  def test_can_be_constructed_without_arguments(self):
    tc = TestConfig()
    assert tc is not None

  def test_custom_values(self):
    tc = TestConfig(suite="my_suite", model="gpt-oss:20b-cloud", repeats=5, compare="base.yaml")
    assert tc.suite == "my_suite"
    assert tc.model == "gpt-oss:20b-cloud"
    assert tc.repeats == 5
    assert tc.compare == "base.yaml"


class TestResolveSuitePath:
  """Tests for _resolve_suite_path."""

  def test_direct_path_to_existing_file(self, tmp_path):
    suite_file = tmp_path / "suite.yaml"
    suite_file.write_text("suite: test")
    result = _resolve_suite_path(str(suite_file))
    assert result == suite_file.resolve()

  def test_suite_name_resolves_to_suites_dir(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    suite_dir = tmp_path / "suites" / "my_suite"
    suite_dir.mkdir(parents=True)
    suite_file = suite_dir / "suite.yaml"
    suite_file.write_text("suite: my_suite")
    result = _resolve_suite_path("my_suite")
    assert result == suite_file.resolve()

  def test_missing_suite_name_raises_filenotfound(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="Suite not found"):
      _resolve_suite_path("nonexistent")

  def test_missing_explicit_path_with_suffix_raises(self):
    with pytest.raises(FileNotFoundError, match="Suite file not found"):
      _resolve_suite_path("/nonexistent/path/to/suite.yaml")


class TestLoadBaseline:
  """Tests for _load_baseline."""

  def _make_report_dict(self) -> dict:
    return {
      "run": {
        "suite": "yoker_basic",
        "suite_version": "1.0",
        "model": "glm-5.2:cloud",
        "provider": "ollama",
        "yoker_version": "0.10.1",
        "temperature": 0.0,
        "seed": 42,
        "repeats": 3,
        "timestamp": "2025-01-15T12:00:00Z",
      },
      "results": [
        {
          "task_id": "K1",
          "category": "knowledge",
          "score": 1.0,
          "response": "C",
          "extracted": "C",
        }
      ],
      "summary": {
        "knowledge": {
          "score": 1.0,
          "std": 0.0,
          "n_tasks": 1,
          "avg_tokens_in": 10.0,
          "avg_tokens_out": 5.0,
          "avg_latency_ms": 42.0,
          "total_tokens": 15,
          "total_latency_s": 0.042,
        }
      },
      "overall": {
        "score": 1.0,
        "std": 0.0,
        "total_tokens_in": 10,
        "total_tokens_out": 5,
        "total_tokens": 15,
        "total_latency_s": 0.042,
        "avg_tokens_per_second": 357.14,
      },
    }

  def test_load_from_yaml(self, tmp_path):
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text(yaml.dump(self._make_report_dict()))
    report = _load_baseline(str(baseline_file))
    assert isinstance(report, TestReport)
    assert report.run.model == "glm-5.2:cloud"
    assert len(report.results) == 1
    assert report.results[0].task_id == "K1"
    assert report.overall is not None
    assert report.overall.score == 1.0

  def test_load_from_json(self, tmp_path):
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps(self._make_report_dict()))
    report = _load_baseline(str(baseline_file))
    assert isinstance(report, TestReport)
    assert report.run.model == "glm-5.2:cloud"
    assert report.overall is not None

  def test_load_with_comparison(self, tmp_path):
    data = self._make_report_dict()
    data["comparison"] = {
      "baseline": data["run"],
      "delta": {"knowledge": -0.05},
      "flagged": ["knowledge"],
    }
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text(yaml.dump(data))
    report = _load_baseline(str(baseline_file))
    assert report.comparison is not None
    assert report.comparison.delta == {"knowledge": -0.05}
    assert report.comparison.flagged == ["knowledge"]


class TestEvaluate:
  """Tests for the evaluate() orchestration function."""

  def _make_suite_yaml(self, tmp_path) -> Path:
    """Create a minimal valid suite YAML file."""
    suite_dir = tmp_path / "suites" / "test_suite"
    suite_dir.mkdir(parents=True)
    suite_file = suite_dir / "suite.yaml"
    suite_file.write_text(
      yaml.dump(
        {
          "suite": "test_suite",
          "version": "1.0",
          "description": "A test suite",
          "repeats": 3,
          "temperature": 0.0,
          "seed": 42,
          "tasks": [
            {
              "id": "K1",
              "category": "knowledge",
              "prompt": "What is 2+2? Reply with just the number.",
              "expected": "4",
              "scorer": "numeric_match",
            }
          ],
        }
      )
    )
    return suite_file

  def _make_mock_config(self) -> MagicMock:
    config = MagicMock()
    config.backend.config.model = "old-model"
    config.backend.provider = "ollama"
    return config

  def _make_mock_report(self) -> TestReport:
    run = RunMetadata(
      suite="test_suite",
      suite_version="1.0",
      model="test-model",
      provider="ollama",
      yoker_version="0.10.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-15T12:00:00Z",
    )
    return TestReport(run=run)

  async def test_evaluate_returns_test_report(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)
    mock_config = self._make_mock_config()
    mock_report = self._make_mock_report()

    with patch("yoker_test.config.EvalRunner") as mock_runner_cls:
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      result = await evaluate("test_suite", "test-model", config=mock_config)

    assert isinstance(result, TestReport)
    assert result.run.model == "test-model"

  async def test_evaluate_sets_model_on_config(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)
    mock_config = self._make_mock_config()
    mock_config.backend.config.model = "old-model"
    mock_report = self._make_mock_report()

    with patch("yoker_test.config.EvalRunner") as mock_runner_cls:
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      await evaluate("test_suite", "new-model", config=mock_config)

    assert mock_config.backend.config.model == "new-model"

  async def test_evaluate_creates_runner_with_correct_params(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)
    mock_config = self._make_mock_config()
    mock_report = self._make_mock_report()

    with patch("yoker_test.config.EvalRunner") as mock_runner_cls:
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      await evaluate("test_suite", "test-model", config=mock_config)

    # Verify runner was constructed with suite config values
    call_args = mock_runner_cls.call_args
    assert call_args.kwargs["repeats"] == 3
    assert call_args.kwargs["temperature"] == 0.0
    assert call_args.kwargs["seed"] == 42
    assert call_args.kwargs["suite_name"] == "test_suite"
    assert call_args.kwargs["suite_version"] == "1.0"
    assert len(call_args.kwargs["tasks"]) == 1

  async def test_evaluate_calls_get_yoker_config_when_config_none(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)
    mock_config = self._make_mock_config()
    mock_report = self._make_mock_report()

    with (
      patch("yoker_test.config.EvalRunner") as mock_runner_cls,
      patch("yoker_test.config.get_yoker_config", return_value=mock_config),
    ):
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      await evaluate("test_suite", "test-model")

    assert mock_config.backend.config.model == "test-model"

  async def test_evaluate_forwards_verbose_to_runner(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)
    mock_config = self._make_mock_config()
    mock_report = self._make_mock_report()

    with patch("yoker_test.config.EvalRunner") as mock_runner_cls:
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      await evaluate("test_suite", "test-model", config=mock_config, verbose=True)

    assert mock_runner.run.call_args.kwargs["verbose"] is True

  async def test_evaluate_with_repeats_override(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)
    mock_config = self._make_mock_config()
    mock_report = self._make_mock_report()

    with patch("yoker_test.config.EvalRunner") as mock_runner_cls:
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      await evaluate("test_suite", "test-model", config=mock_config, repeats=10)

    call_args = mock_runner_cls.call_args
    assert call_args.kwargs["repeats"] == 10

  async def test_evaluate_invalid_suite_raises_valueerror(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    suite_dir = tmp_path / "suites" / "bad_suite"
    suite_dir.mkdir(parents=True)
    suite_file = suite_dir / "suite.yaml"
    # Missing required fields
    suite_file.write_text(yaml.dump({"suite": "", "version": "1.0", "description": "d"}))

    mock_config = self._make_mock_config()

    with pytest.raises(ValueError, match="Suite validation failed"):
      await evaluate("bad_suite", "test-model", config=mock_config)

  async def test_evaluate_with_compare_attaches_comparison(self, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    self._make_suite_yaml(tmp_path)

    # Create a baseline file
    baseline_data = {
      "run": {
        "suite": "test_suite",
        "suite_version": "1.0",
        "model": "old-model",
        "provider": "ollama",
        "yoker_version": "0.10.1",
        "temperature": 0.0,
        "seed": 42,
        "repeats": 3,
        "timestamp": "2025-01-01T00:00:00Z",
      },
      "results": [],
      "summary": {
        "knowledge": {
          "score": 0.8,
          "std": 0.05,
          "n_tasks": 1,
          "avg_tokens_in": 10.0,
          "avg_tokens_out": 5.0,
          "avg_latency_ms": 42.0,
          "total_tokens": 15,
          "total_latency_s": 0.042,
        }
      },
    }
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text(yaml.dump(baseline_data))

    mock_config = self._make_mock_config()

    # Build a report with matching summary for comparison
    run = RunMetadata(
      suite="test_suite",
      suite_version="1.0",
      model="test-model",
      provider="ollama",
      yoker_version="0.10.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-15T12:00:00Z",
    )
    mock_report = TestReport(
      run=run,
      summary={
        "knowledge": CategorySummary(
          score=0.9,
          std=0.05,
          n_tasks=1,
          avg_tokens_in=10.0,
          avg_tokens_out=5.0,
          avg_latency_ms=42.0,
          total_tokens=15,
          total_latency_s=0.042,
        )
      },
    )

    with patch("yoker_test.config.EvalRunner") as mock_runner_cls:
      mock_runner = MagicMock()
      mock_runner.run = AsyncMock(return_value=mock_report)
      mock_runner_cls.return_value = mock_runner

      result = await evaluate(
        "test_suite", "test-model", compare=str(baseline_file), config=mock_config
      )

    assert result.comparison is not None
    assert isinstance(result.comparison, ComparisonReport)
    assert "knowledge" in result.comparison.delta


class TestTestReportFromDict:
  """Tests for TestReport.from_dict()."""

  def _make_report(self) -> TestReport:
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
    )
    return TestReport(run=run, results=results, summary=summary, overall=overall)

  def test_round_trip_to_dict_from_dict(self):
    report = self._make_report()
    d = report.to_dict()
    restored = TestReport.from_dict(d)
    assert restored.run.model == report.run.model
    assert restored.run.suite == report.run.suite
    assert len(restored.results) == len(report.results)
    assert restored.results[0].task_id == report.results[0].task_id
    assert restored.results[0].score == report.results[0].score
    assert "knowledge" in restored.summary
    assert restored.summary["knowledge"].score == report.summary["knowledge"].score
    assert restored.overall is not None
    assert restored.overall.score == report.overall.score
    assert restored.comparison is None

  def test_from_dict_with_extra_keys_ignored(self):
    report = self._make_report()
    d = report.to_dict()
    d["run"]["extra_key"] = "ignored"
    d["results"][0]["extra_field"] = 999
    d["extra_top_level"] = True
    restored = TestReport.from_dict(d)
    assert restored.run.model == report.run.model
    assert len(restored.results) == 1

  def test_from_dict_with_missing_optional_fields(self):
    d = {
      "run": {
        "suite": "s",
        "suite_version": "1",
        "model": "m",
        "provider": "p",
        "yoker_version": "0.1",
        "temperature": 0.0,
        "seed": 42,
        "repeats": 3,
        "timestamp": "2025-01-01",
      },
      "results": [],
    }
    restored = TestReport.from_dict(d)
    assert restored.run.model == "m"
    assert restored.results == []
    assert restored.summary == {}
    assert restored.overall is None
    assert restored.comparison is None

  def test_from_dict_with_comparison(self):
    report = self._make_report()
    d = report.to_dict()
    d["comparison"] = {
      "baseline": d["run"],
      "delta": {"knowledge": -0.1},
      "flagged": ["knowledge"],
    }
    restored = TestReport.from_dict(d)
    assert restored.comparison is not None
    assert restored.comparison.baseline.model == "glm-5.2:cloud"
    assert restored.comparison.delta == {"knowledge": -0.1}
    assert restored.comparison.flagged == ["knowledge"]


class TestPublicAPIExports:
  """Tests that the public API exports from __init__.py work."""

  def test_import_evaluate(self):
    from yoker_test import evaluate

    assert callable(evaluate)

  def test_import_eval_runner(self):
    from yoker_test import EvalRunner

    assert EvalRunner is not None

  def test_import_test_task(self):
    from yoker_test import TestTask

    assert TestTask is not None

  def test_import_test_report(self):
    from yoker_test import TestReport

    assert TestReport is not None

  def test_import_score(self):
    from yoker_test import Score

    assert Score is not None

  def test_import_test_config(self):
    from yoker_test import TestConfig

    assert TestConfig is not None

  def test_import_suite_config(self):
    from yoker_test import SuiteConfig

    assert SuiteConfig is not None

  def test_import_comparison_report(self):
    from yoker_test import ComparisonReport

    assert ComparisonReport is not None

  def test_all_exports_listed(self):
    import yoker_test

    expected = {
      "__version__",
      "__author__",
      "evaluate",
      "TestConfig",
      "EvalRunner",
      "TestTask",
      "TestReport",
      "Score",
      "SuiteConfig",
      "ComparisonReport",
    }
    assert set(yoker_test.__all__) == expected
