"""Tests for yoker_test.runner."""

from unittest.mock import AsyncMock, MagicMock, patch

from yoker_test.runner import StatsCollector, run_single_test
from yoker_test.schema import TestTask


class TestStatsCollectorTurnEnd:
  """Tests for StatsCollector processing TurnEndEvent."""

  def test_captures_token_counts(self):
    collector = StatsCollector()
    event = MagicMock()
    event.type = MagicMock()
    # Simulate TurnEndEvent attributes
    event.input_tokens = 100
    event.output_tokens = 50
    event.prompt_eval_count = 110
    event.eval_count = 55
    event.total_duration_ms = 1234.0

    # We need to patch EventType comparison
    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_END = event.type
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content"
      collector(event)

    assert collector.stats["input_tokens"] == 100
    assert collector.stats["output_tokens"] == 50
    assert collector.stats["prompt_eval_count"] == 110
    assert collector.stats["eval_count"] == 55
    assert collector.stats["total_duration_ms"] == 1234.0

  def test_none_values_become_zero(self):
    collector = StatsCollector()
    event = MagicMock()
    event.input_tokens = None
    event.output_tokens = None
    event.prompt_eval_count = None
    event.eval_count = None
    event.total_duration_ms = None

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_END = event.type
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content"
      collector(event)

    assert collector.stats["input_tokens"] == 0
    assert collector.stats["output_tokens"] == 0
    assert collector.stats["prompt_eval_count"] == 0
    assert collector.stats["eval_count"] == 0
    assert collector.stats["total_duration_ms"] == 0


class TestStatsCollectorChunkEvents:
  """Tests for StatsCollector processing chunk events."""

  def test_thinking_chunk_accumulates_chars(self):
    collector = StatsCollector()
    event1 = MagicMock()
    event1.type = "thinking_chunk"
    event1.text = "Hello "
    event2 = MagicMock()
    event2.type = "thinking_chunk"
    event2.text = "World"

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking_chunk"
      mock_et.CONTENT_CHUNK = "content"
      collector(event1)
      collector(event2)

    assert collector.thinking_chars == 11

  def test_content_chunk_accumulates_chars(self):
    collector = StatsCollector()
    event1 = MagicMock()
    event1.type = "content_chunk"
    event1.text = "Answer: "
    event2 = MagicMock()
    event2.type = "content_chunk"
    event2.text = "C"

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content_chunk"
      collector(event1)
      collector(event2)

    assert collector.content_chars == 9

  def test_empty_text_chunk_adds_zero(self):
    collector = StatsCollector()
    event = MagicMock()
    event.text = ""

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = event.type
      collector(event)

    assert collector.content_chars == 0

  def test_unknown_event_type_ignored(self):
    collector = StatsCollector()
    event = MagicMock()
    event.type = "unknown_event"

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content"
      collector(event)

    assert collector.stats == {}
    assert collector.thinking_chars == 0
    assert collector.content_chars == 0


class TestStatsCollectorInitialState:
  """Tests for StatsCollector initial state."""

  def test_empty_stats_on_init(self):
    collector = StatsCollector()
    assert collector.stats == {}

  def test_zero_thinking_chars_on_init(self):
    collector = StatsCollector()
    assert collector.thinking_chars == 0

  def test_zero_content_chars_on_init(self):
    collector = StatsCollector()
    assert collector.content_chars == 0


def make_task(expected: str = "C") -> TestTask:
  return TestTask(id="K1", category="knowledge", prompt="?", expected=expected, scorer="mcq")


class TestRunSingleTest:
  """Tests for run_single_test."""

  async def test_successful_run(self):
    task = make_task(expected="C")

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value="C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.task_id == "K1"
    assert result.category == "knowledge"
    assert result.score == 1.0
    assert result.response == "C"
    assert result.extracted == "C"
    assert result.error is None

  async def test_incorrect_answer(self):
    task = make_task(expected="C")

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value="B")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.score == 0.0
    assert result.extracted == "B"

  async def test_agent_error_returns_error_result(self):
    task = make_task(expected="C")

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(side_effect=RuntimeError("Connection failed"))

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.score == 0.0
    assert result.extracted is None
    assert result.error == "Connection failed"
    assert result.response == ""

  async def test_tokens_normalized_from_openai_fields(self):
    """When input_tokens/output_tokens are set, those are used."""
    task = make_task()

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value="C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      with patch("yoker_test.runner.StatsCollector") as mock_collector_cls:
        collector_instance = MagicMock()
        collector_instance.stats = {
          "input_tokens": 200,
          "output_tokens": 80,
          "prompt_eval_count": 250,
          "eval_count": 90,
          "total_duration_ms": 500.0,
        }
        collector_instance.thinking_chars = 0
        collector_instance.content_chars = 1
        mock_collector_cls.return_value = collector_instance

        result = await run_single_test(task, config=MagicMock())

    assert result.tokens_in == 200
    assert result.tokens_out == 80
    assert result.latency_ms == 500.0

  async def test_tokens_fall_back_to_ollama_fields(self):
    """When input_tokens/output_tokens are 0, fall back to prompt_eval_count/eval_count."""
    task = make_task()

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value="C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      with patch("yoker_test.runner.StatsCollector") as mock_collector_cls:
        collector_instance = MagicMock()
        collector_instance.stats = {
          "input_tokens": 0,
          "output_tokens": 0,
          "prompt_eval_count": 300,
          "eval_count": 120,
          "total_duration_ms": 0,
        }
        collector_instance.thinking_chars = 0
        collector_instance.content_chars = 1
        mock_collector_cls.return_value = collector_instance

        result = await run_single_test(task, config=MagicMock())

    assert result.tokens_in == 300
    assert result.tokens_out == 120

  async def test_latency_falls_back_to_wall_clock(self):
    """When total_duration_ms is 0, latency falls back to wall-clock time."""
    task = make_task()

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value="C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      with patch("yoker_test.runner.StatsCollector") as mock_collector_cls:
        collector_instance = MagicMock()
        collector_instance.stats = {
          "input_tokens": 10,
          "output_tokens": 5,
          "prompt_eval_count": 0,
          "eval_count": 0,
          "total_duration_ms": 0,
        }
        collector_instance.thinking_chars = 0
        collector_instance.content_chars = 1
        mock_collector_cls.return_value = collector_instance

        result = await run_single_test(task, config=MagicMock())

    # Wall clock should be > 0 (very small but positive)
    assert result.latency_ms > 0

  async def test_response_is_stripped(self):
    task = make_task(expected="C")

    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value="  C  \n")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.response == "C"
