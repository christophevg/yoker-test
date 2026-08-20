"""Tests for yoker_test.cli."""

from unittest.mock import AsyncMock, MagicMock, patch

from yoker_test.cli import async_main, main


class TestMainArgumentParsing:
  """Tests for the main() CLI entry point."""

  def test_default_model(self):
    with (
      patch("yoker_test.cli.asyncio.run", return_value=0) as mock_run,
      patch("sys.argv", ["yoker-test"]),
      patch("sys.exit") as mock_exit,
    ):
      main()
      mock_run.assert_called_once()
      mock_exit.assert_called_once_with(0)

  def test_custom_model(self):
    with (
      patch("yoker_test.cli.asyncio.run", return_value=0) as mock_run,
      patch("sys.argv", ["yoker-test", "--model", "gpt-4"]),
      patch("sys.exit") as mock_exit,
    ):
      main()
      mock_run.assert_called_once()
      mock_exit.assert_called_once_with(0)

  def test_exits_with_return_code(self):
    with (
      patch("yoker_test.cli.asyncio.run", return_value=0) as mock_run,
      patch("sys.argv", ["yoker-test"]),
      patch("sys.exit") as mock_exit,
    ):
      main()
      mock_run.assert_called_once()
      mock_exit.assert_called_once_with(0)


class TestAsyncMain:
  """Tests for async_main orchestration."""

  async def test_successful_run_returns_zero(self):
    mock_config = MagicMock()
    mock_result = MagicMock()
    mock_result.error = None

    with (
      patch("yoker_test.cli.get_yoker_config", return_value=mock_config),
      patch("yoker_test.cli.fetch_ollama_usage", new_callable=AsyncMock, return_value=None),
      patch("yoker_test.cli.run_single_test", new_callable=AsyncMock, return_value=mock_result),
      patch("yoker_test.cli.print_report", return_value=1.0),
    ):
      ret = await async_main("test-model")

    assert ret == 0

  async def test_error_run_returns_one(self):
    mock_config = MagicMock()
    mock_result = MagicMock()
    mock_result.error = "Something went wrong"

    with (
      patch("yoker_test.cli.get_yoker_config", return_value=mock_config),
      patch("yoker_test.cli.fetch_ollama_usage", new_callable=AsyncMock, return_value=None),
      patch("yoker_test.cli.run_single_test", new_callable=AsyncMock, return_value=mock_result),
      patch("yoker_test.cli.print_report", return_value=0.0),
    ):
      ret = await async_main("test-model")

    assert ret == 1

  async def test_config_model_override(self):
    """Config should have model overridden and validated."""
    mock_config = MagicMock()

    with (
      patch("yoker_test.cli.get_yoker_config", return_value=mock_config),
      patch("yoker_test.cli.fetch_ollama_usage", new_callable=AsyncMock, return_value=None),
      patch(
        "yoker_test.cli.run_single_test", new_callable=AsyncMock, return_value=MagicMock(error=None)
      ),
      patch("yoker_test.cli.print_report", return_value=1.0),
    ):
      await async_main("my-custom-model")

    assert mock_config.backend.config.model == "my-custom-model"
    mock_config.backend.validate.assert_called_once()

  async def test_fetches_usage_before_and_after(self):
    mock_config = MagicMock()
    mock_result = MagicMock()
    mock_result.error = None

    with (
      patch("yoker_test.cli.get_yoker_config", return_value=mock_config),
      patch("yoker_test.cli.fetch_ollama_usage", new_callable=AsyncMock) as mock_fetch,
      patch("yoker_test.cli.run_single_test", new_callable=AsyncMock, return_value=mock_result),
      patch("yoker_test.cli.print_report", return_value=1.0),
    ):
      await async_main("test-model")

    assert mock_fetch.call_count == 2

  async def test_prints_header(self, capsys):
    mock_config = MagicMock()
    mock_result = MagicMock()
    mock_result.error = None

    with (
      patch("yoker_test.cli.get_yoker_config", return_value=mock_config),
      patch("yoker_test.cli.fetch_ollama_usage", new_callable=AsyncMock, return_value=None),
      patch("yoker_test.cli.run_single_test", new_callable=AsyncMock, return_value=mock_result),
      patch("yoker_test.cli.print_report", return_value=1.0),
    ):
      await async_main("test-model")

    output = capsys.readouterr().out
    assert "yoker-test — model: test-model" in output
    assert "Task:" in output
    assert "Prompt:" in output

  async def test_passes_usage_to_report(self):
    mock_config = MagicMock()
    mock_result = MagicMock()
    mock_result.error = None
    usage_before = {"session": 0.1, "weekly": 0.5}
    usage_after = {"session": 0.12, "weekly": 0.51}

    with (
      patch("yoker_test.cli.get_yoker_config", return_value=mock_config),
      patch(
        "yoker_test.cli.fetch_ollama_usage",
        new_callable=AsyncMock,
        side_effect=[usage_before, usage_after],
      ),
      patch("yoker_test.cli.run_single_test", new_callable=AsyncMock, return_value=mock_result),
      patch("yoker_test.cli.print_report") as mock_report,
    ):
      await async_main("test-model")

    mock_report.assert_called_once()
    _, kwargs = mock_report.call_args
    # positional args: task, result, usage_before, usage_after
    args = mock_report.call_args.args
    assert args[2] == usage_before
    assert args[3] == usage_after
