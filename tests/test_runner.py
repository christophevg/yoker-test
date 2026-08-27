"""Tests for yoker_test.runner."""

from unittest.mock import AsyncMock, MagicMock, patch

from yoker_test.runner import EvalRunner, StatsCollector, run_single_test
from yoker_test.schema import TestReport, TestTask


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


def make_mock_agent(process_return: str = "C", process_side_effect=None) -> MagicMock:
  """Create a mock agent with async process() and aclose() methods."""
  agent = MagicMock()
  if process_side_effect is not None:
    agent.process = AsyncMock(side_effect=process_side_effect)
  else:
    agent.process = AsyncMock(return_value=process_return)
  agent.aclose = AsyncMock()
  return agent


class TestRunSingleTest:
  """Tests for run_single_test."""

  async def test_successful_run(self):
    task = make_task(expected="C")

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.task_id == "K1"
    assert result.category == "knowledge"
    assert result.score == 1.0
    assert result.response == "C"
    assert result.extracted is None
    assert result.error is None

  async def test_incorrect_answer(self):
    task = make_task(expected="C")

    mock_agent = make_mock_agent("B")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.score == 0.0
    assert result.extracted is None

  async def test_agent_error_returns_error_result(self):
    task = make_task(expected="C")

    mock_agent = make_mock_agent(process_side_effect=RuntimeError("Connection failed"))

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.score == 0.0
    assert result.extracted is None
    assert result.error == "Connection failed"
    assert result.response == ""

  async def test_tokens_normalized_from_openai_fields(self):
    """When input_tokens/output_tokens are set, those are used."""
    task = make_task()

    mock_agent = make_mock_agent("C")

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

    mock_agent = make_mock_agent("C")

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

    mock_agent = make_mock_agent("C")

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

    mock_agent = make_mock_agent("  C  \n")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      result = await run_single_test(task, config=MagicMock())

    assert result.response == "C"


class TestStatsCollectorTTFT:
  """Tests for StatsCollector TTFT (time to first token) capture."""

  def test_turn_start_captures_timestamp(self):
    collector = StatsCollector()
    event = MagicMock()
    event.type = "turn_start"

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_START = "turn_start"
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content"
      mock_et.CONTENT_START = "content_start"
      collector(event)

    assert collector.turn_start_time is not None

  def test_content_start_captures_timestamp(self):
    collector = StatsCollector()
    event = MagicMock()
    event.type = "content_start"

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_START = "turn_start"
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content"
      mock_et.CONTENT_START = "content_start"
      collector(event)

    assert collector.content_start_time is not None

  def test_ttft_ms_is_none_without_any_timestamps(self):
    collector = StatsCollector()
    assert collector.ttft_ms is None

  def test_ttft_ms_is_none_with_only_turn_start(self):
    collector = StatsCollector()
    collector.turn_start_time = 1.0
    assert collector.ttft_ms is None

  def test_ttft_ms_is_none_with_only_content_start(self):
    collector = StatsCollector()
    collector.content_start_time = 2.0
    assert collector.ttft_ms is None

  def test_ttft_ms_calculated_from_both_timestamps(self):
    collector = StatsCollector()
    collector.turn_start_time = 1.0
    collector.content_start_time = 1.5
    # (1.5 - 1.0) * 1000 = 500.0 ms
    assert collector.ttft_ms == 500.0

  def test_ttft_ms_is_zero_when_timestamps_equal(self):
    collector = StatsCollector()
    collector.turn_start_time = 2.0
    collector.content_start_time = 2.0
    assert collector.ttft_ms == 0.0

  def test_ttft_ms_full_event_sequence(self):
    """Simulate a full event stream and verify TTFT is captured."""
    collector = StatsCollector()

    turn_start_event = MagicMock()
    turn_start_event.type = "turn_start"
    content_start_event = MagicMock()
    content_start_event.type = "content_start"
    turn_end_event = MagicMock()
    turn_end_event.type = "turn_end"
    turn_end_event.input_tokens = 10
    turn_end_event.output_tokens = 5
    turn_end_event.prompt_eval_count = 0
    turn_end_event.eval_count = 0
    turn_end_event.total_duration_ms = 100

    with patch("yoker_test.runner.EventType") as mock_et:
      mock_et.TURN_START = "turn_start"
      mock_et.TURN_END = "turn_end"
      mock_et.THINKING_CHUNK = "thinking"
      mock_et.CONTENT_CHUNK = "content"
      mock_et.CONTENT_START = "content_start"

      collector(turn_start_event)
      collector(content_start_event)
      collector(turn_end_event)

    assert collector.ttft_ms is not None
    assert collector.ttft_ms >= 0.0
    assert collector.stats["input_tokens"] == 10


def make_mock_config(provider: str = "ollama") -> MagicMock:
  """Create a mock config with a backend for EvalRunner tests."""
  config = MagicMock()
  config.backend.provider = provider
  config.backend.config.model = "old-model"
  return config


class TestEvalRunnerInit:
  """Tests for EvalRunner construction."""

  def test_default_values(self):
    runner = EvalRunner(tasks=[])
    assert runner._repeats == 3
    assert runner._temperature == 0.0
    assert runner._seed == 42
    assert runner._suite_name == ""
    assert runner._suite_version == ""
    assert runner._weights is None

  def test_custom_values(self):
    runner = EvalRunner(
      tasks=[],
      repeats=5,
      temperature=0.7,
      seed=99,
      suite_name="test-suite",
      suite_version="1.0.0",
      aggregation_weights={"knowledge": 2.0},
    )
    assert runner._repeats == 5
    assert runner._temperature == 0.7
    assert runner._seed == 99
    assert runner._suite_name == "test-suite"
    assert runner._suite_version == "1.0.0"
    assert runner._weights == {"knowledge": 2.0}

  def test_tasks_stored(self):
    tasks = [make_task(), make_task(expected="A")]
    runner = EvalRunner(tasks=tasks)
    assert len(runner._tasks) == 2


class TestEvalRunnerRun:
  """Tests for EvalRunner.run() — multi-task × multi-repeat execution."""

  async def test_single_task_single_repeat(self):
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert isinstance(report, TestReport)
    assert len(report.results) == 1
    assert report.results[0].score == 1.0
    assert report.results[0].repeat == 0

  async def test_single_task_multiple_repeats(self):
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=3)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert len(report.results) == 3
    assert all(r.score == 1.0 for r in report.results)
    assert report.results[0].repeat == 0
    assert report.results[1].repeat == 1
    assert report.results[2].repeat == 2

  async def test_multiple_tasks_multiple_repeats(self):
    task1 = make_task(expected="C")
    task1.id = "K1"
    task2 = make_task(expected="A")
    task2.id = "K2"
    runner = EvalRunner(tasks=[task1, task2], repeats=2)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert len(report.results) == 4
    # task-major, repeat-minor ordering: K1×0, K1×1, K2×0, K2×1
    assert report.results[0].task_id == "K1"
    assert report.results[0].repeat == 0
    assert report.results[1].task_id == "K1"
    assert report.results[1].repeat == 1
    assert report.results[2].task_id == "K2"
    assert report.results[2].repeat == 0
    assert report.results[3].task_id == "K2"
    assert report.results[3].repeat == 1

  async def test_error_isolation_one_task_fails(self):
    """One task failure does NOT abort the suite."""
    task1 = make_task(expected="C")
    task1.id = "K1"
    task2 = make_task(expected="A")
    task2.id = "K2"
    runner = EvalRunner(tasks=[task1, task2], repeats=1)

    call_count = 0

    async def mock_process(prompt):
      nonlocal call_count
      call_count += 1
      if call_count == 1:
        raise RuntimeError("Connection failed")
      return "A"

    mock_agent = MagicMock()
    mock_agent.process = mock_process
    mock_agent.aclose = AsyncMock()

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert len(report.results) == 2
    assert report.results[0].error == "Connection failed"
    assert report.results[0].score == 0.0
    assert report.results[1].error is None
    assert report.results[1].score == 1.0

  async def test_empty_response_detected_as_refusal(self):
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("   ")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert len(report.results) == 1
    assert report.results[0].error == "refused: empty response"
    assert report.results[0].score == 0.0
    assert report.results[0].response == ""

  async def test_metadata_collected(self):
    task = make_task(expected="C")
    runner = EvalRunner(
      tasks=[task],
      repeats=2,
      temperature=0.5,
      seed=123,
      suite_name="my-suite",
      suite_version="2.0.0",
    )

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      with patch("yoker_test.runner.yoker.__version__", "0.10.1"):
        report = await runner.run("test-model", make_mock_config(provider="openai"))

    assert report.run.suite == "my-suite"
    assert report.run.suite_version == "2.0.0"
    assert report.run.model == "test-model"
    assert report.run.provider == "openai"
    assert report.run.yoker_version == "0.10.1"
    assert report.run.temperature == 0.5
    assert report.run.seed == 123
    assert report.run.repeats == 2
    assert report.run.timestamp is not None

  async def test_config_model_set_from_run_parameter(self):
    """run() should set config.backend.config.model from the model parameter."""
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)
    config = make_mock_config()
    config.backend.config.model = "old-model"

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      await runner.run("new-model", config)

    assert config.backend.config.model == "new-model"

  async def test_scorer_name_captured_for_string_scorer(self):
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert report.results[0].scorer_name == "mcq"

  async def test_scorer_name_captured_for_callable_scorer(self):
    def custom_scorer(task, response):
      from yoker_test.schema import Score

      return Score(value=1.0, extracted="C", sub_scores=None)

    task = TestTask(id="K1", category="knowledge", prompt="?", expected="C", scorer=custom_scorer)
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert report.results[0].scorer_name == "custom_scorer"

  async def test_prompt_stored_in_result(self):
    task = make_task(expected="C")
    task.prompt = "What is 2+2?"
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert report.results[0].prompt == "What is 2+2?"

  async def test_difficulty_stored_in_result(self):
    task = make_task(expected="C")
    task.difficulty = "hard"
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert report.results[0].difficulty == "hard"

  async def test_summary_populated_after_run(self):
    """run() populates summary and overall via aggregation."""
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      report = await runner.run("test-model", make_mock_config())

    assert report.summary != {}
    assert "knowledge" in report.summary
    assert report.overall is not None
    assert report.overall.score == 1.0

  async def test_ttft_captured_when_events_present(self):
    """TTFT is captured from TURN_START and CONTENT_START events."""
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      with patch("yoker_test.runner.StatsCollector") as mock_collector_cls:
        collector_instance = MagicMock()
        collector_instance.stats = {
          "input_tokens": 10,
          "output_tokens": 5,
          "prompt_eval_count": 0,
          "eval_count": 0,
          "total_duration_ms": 100,
        }
        collector_instance.thinking_chars = 0
        collector_instance.content_chars = 1
        collector_instance.ttft_ms = 42.5
        mock_collector_cls.return_value = collector_instance

        report = await runner.run("test-model", make_mock_config())

    assert report.results[0].ttft_ms == 42.5

  async def test_ttft_none_when_events_absent(self):
    """TTFT is None when TURN_START/CONTENT_START events are not captured."""
    task = make_task(expected="C")
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent):
      with patch("yoker_test.runner.StatsCollector") as mock_collector_cls:
        collector_instance = MagicMock()
        collector_instance.stats = {
          "input_tokens": 10,
          "output_tokens": 5,
          "prompt_eval_count": 0,
          "eval_count": 0,
          "total_duration_ms": 100,
        }
        collector_instance.thinking_chars = 0
        collector_instance.content_chars = 1
        collector_instance.ttft_ms = None
        mock_collector_cls.return_value = collector_instance

        report = await runner.run("test-model", make_mock_config())

    assert report.results[0].ttft_ms is None

  async def test_zero_tasks_returns_empty_results(self):
    runner = EvalRunner(tasks=[], repeats=3)

    report = await runner.run("test-model", make_mock_config())

    assert len(report.results) == 0
    assert report.run.model == "test-model"

  async def test_system_prompt_passed_to_agent(self):
    """When a task has a system_prompt, it's passed to yoker.agent()."""
    task = TestTask(
      id="K1",
      category="knowledge",
      prompt="?",
      expected="C",
      scorer="mcq",
      system_prompt="You are a helpful assistant.",
    )
    runner = EvalRunner(tasks=[task], repeats=1)

    mock_agent = make_mock_agent("C")

    with patch("yoker_test.runner.yoker.agent", return_value=mock_agent) as mock_factory:
      await runner.run("test-model", make_mock_config())

    _, kwargs = mock_factory.call_args
    assert kwargs["system_prompt"] == "You are a helpful assistant."
