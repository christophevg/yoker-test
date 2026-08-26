"""Schema for yoker-test: core dataclasses for tasks, results, and reports."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml


@dataclass
class TestTask:
  __test__ = False

  id: str
  category: str
  prompt: str
  expected: Any
  scorer: str | Callable
  difficulty: str = ""
  system_prompt: str | None = None
  scorer_config: dict = field(default_factory=dict)


@dataclass
class Score:
  __test__ = False

  value: float
  extracted: str | None = None
  sub_scores: dict[str, float] | None = None
  explanation: str | None = None


@dataclass
class TestResult:
  __test__ = False

  task_id: str
  category: str
  score: float
  response: str
  extracted: str | None = None
  tokens_in: int | None = 0
  tokens_out: int | None = 0
  latency_ms: float = 0.0
  thinking_chars: int = 0
  content_chars: int = 0
  error: str | None = None
  difficulty: str = ""
  repeat: int = 0
  prompt: str = ""
  messages: list[dict] = field(default_factory=list)
  ttft_ms: float | None = None
  scorer_name: str = ""
  sub_scores: dict[str, float] | None = None


@dataclass
class RunMetadata:
  __test__ = False

  suite: str
  suite_version: str
  model: str
  provider: str
  yoker_version: str
  temperature: float
  seed: int
  repeats: int
  timestamp: str


@dataclass
class SuiteConfig:
  __test__ = False

  suite: str
  version: str
  description: str
  repeats: int = 3
  temperature: float = 0.0
  seed: int = 42
  max_tokens: int | None = None
  tasks: list[TestTask] = field(default_factory=list)
  task_generator: Callable | None = None
  generator_config: dict | None = None
  aggregation_weights: dict[str, float] | None = None


@dataclass
class CategorySummary:
  __test__ = False

  score: float
  std: float
  n_tasks: int
  avg_tokens_in: float
  avg_tokens_out: float
  avg_latency_ms: float
  total_tokens: int
  total_latency_s: float


@dataclass
class OverallSummary:
  __test__ = False

  score: float
  std: float
  total_tokens_in: int
  total_tokens_out: int
  total_tokens: int
  total_latency_s: float
  avg_tokens_per_second: float
  usage_delta: dict[str, float] | None = None


@dataclass
class ComparisonReport:
  __test__ = False

  baseline: RunMetadata
  delta: dict[str, float]
  flagged: list[str] = field(default_factory=list)


def _filter_fields(cls: type, data: dict) -> dict:
  """Filter dict to only fields that exist on the dataclass."""
  fields = getattr(cls, "__dataclass_fields__", {})
  return {k: v for k, v in data.items() if k in fields}


@dataclass
class TestReport:
  __test__ = False

  run: RunMetadata
  results: list[TestResult] = field(default_factory=list)
  summary: dict[str, CategorySummary] = field(default_factory=dict)
  overall: OverallSummary | None = None
  comparison: ComparisonReport | None = None

  @classmethod
  def from_dict(cls, data: dict) -> "TestReport":
    """Reconstruct a TestReport from a plain dict (e.g., from YAML/JSON).

    Handles extra/missing keys gracefully via _filter_fields for
    forward/backward compatibility.
    """
    run = RunMetadata(**_filter_fields(RunMetadata, data["run"]))
    results = [TestResult(**_filter_fields(TestResult, r)) for r in data.get("results", [])]
    summary = {
      cat: CategorySummary(**_filter_fields(CategorySummary, s))
      for cat, s in data.get("summary", {}).items()
    }
    overall = None
    if data.get("overall") is not None:
      overall = OverallSummary(**_filter_fields(OverallSummary, data["overall"]))
    comparison = None
    if data.get("comparison") is not None:
      comp_data = data["comparison"]
      baseline = RunMetadata(**_filter_fields(RunMetadata, comp_data["baseline"]))
      comp_fields = _filter_fields(
        ComparisonReport, {k: v for k, v in comp_data.items() if k != "baseline"}
      )
      comparison = ComparisonReport(baseline=baseline, **comp_fields)
    return cls(run=run, results=results, summary=summary, overall=overall, comparison=comparison)

  def to_dict(self) -> dict:
    """Recursively convert to a plain dict."""
    return asdict(self)

  def to_json(self) -> str:
    """Serialize to a JSON string."""
    return json.dumps(self.to_dict(), indent=2, default=str)

  def to_yaml(self) -> str:
    """Serialize to a YAML string."""
    return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)
