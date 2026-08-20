"""Schema for yoker-test: core dataclasses for tasks and results."""

from dataclasses import dataclass, field


@dataclass
class TestTask:
  # Prevent pytest from collecting this as a test class
  __test__ = False

  id: str
  category: str
  prompt: str
  expected: str
  scorer: str
  scorer_config: dict = field(default_factory=dict)


@dataclass
class TestResult:
  # Prevent pytest from collecting this as a test class
  __test__ = False

  task_id: str
  category: str
  score: float
  response: str
  extracted: str | None
  tokens_in: int
  tokens_out: int
  latency_ms: float
  thinking_chars: int = 0
  content_chars: int = 0
  error: str | None = None
