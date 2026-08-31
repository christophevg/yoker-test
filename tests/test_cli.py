"""Tests for yoker_test.cli."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from yoker_test.cli import cmd_eval, cmd_show, cmd_suites, main
from yoker_test.schema import RunMetadata, TestReport


def _mock_report(model: str = "test-model") -> TestReport:
  """Create a minimal TestReport for mocking evaluate()."""
  return TestReport(
    run=RunMetadata(
      suite="test_suite",
      suite_version="1.0",
      model=model,
      provider="ollama",
      yoker_version="0.10.1",
      temperature=0.0,
      seed=42,
      repeats=3,
      timestamp="2025-01-01T00:00:00",
    ),
    results=[],
  )


def _mock_suite_config(
  suite: str = "test_suite",
  version: str = "1.0",
  description: str = "A test suite",
  tasks: list | None = None,
  repeats: int = 3,
  temperature: float = 0.0,
  seed: int = 42,
  max_tokens: int | None = None,
  aggregation_weights: dict[str, float] | None = None,
):
  """Create a mock SuiteConfig-like object."""
  from yoker_test.schema import SuiteConfig, TestTask

  if tasks is None:
    tasks = [
      TestTask(id="T1", category="math", prompt="1+1=?", expected="2", scorer="mcq"),
      TestTask(id="T2", category="logic", prompt="true or false?", expected="true", scorer="mcq"),
    ]

  return SuiteConfig(
    suite=suite,
    version=version,
    description=description,
    tasks=tasks,
    repeats=repeats,
    temperature=temperature,
    seed=seed,
    max_tokens=max_tokens,
    aggregation_weights=aggregation_weights,
  )


class TestEvalSubcommandParsing:
  """Tests for 'eval' subcommand argument parsing."""

  def test_eval_basic(self):
    with (
      patch("yoker_test.cli.asyncio.run", return_value=0),
      patch("sys.argv", ["yoker-test", "eval", "--suite", "my_suite"]),
      patch("sys.exit") as mock_exit,
    ):
      main()
      mock_exit.assert_called_once_with(0)

  def test_eval_with_all_args(self):
    with (
      patch("yoker_test.cli.asyncio.run", return_value=0) as mock_run,
      patch(
        "sys.argv",
        [
          "yoker-test",
          "eval",
          "--suite",
          "my_suite",
          "--model",
          "gpt-4",
          "--compare",
          "baseline.yaml",
          "--output",
          "results.yaml",
          "--repeats",
          "5",
        ],
      ),
      patch("sys.exit"),
    ):
      main()
      coro = mock_run.call_args.args[0]
      assert coro is not None

  def test_eval_missing_suite_arg_exits(self):
    with (
      patch("sys.argv", ["yoker-test", "eval"]),
      pytest.raises(SystemExit) as exc_info,
    ):
      main()
    assert exc_info.value.code == 2

  def test_eval_default_model(self):
    """eval without --model should default to glm-5.2:cloud."""
    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch("sys.argv", ["yoker-test", "eval", "--suite", "my_suite"]),
      patch("sys.exit"),
    ):
      main()
      mock_cmd.assert_called_once_with("my_suite", "glm-5.2:cloud", None, None, None, [], False)


class TestSuitesSubcommandParsing:
  """Tests for 'suites' subcommand argument parsing."""

  def test_suites_dispatch(self):
    with (
      patch("yoker_test.cli.cmd_suites", return_value=0) as mock_cmd,
      patch("sys.argv", ["yoker-test", "suites"]),
      patch("sys.exit") as mock_exit,
    ):
      main()
      mock_cmd.assert_called_once()
      mock_exit.assert_called_once_with(0)


class TestShowSubcommandParsing:
  """Tests for 'show' subcommand argument parsing."""

  def test_show_dispatch(self):
    with (
      patch("yoker_test.cli.cmd_show", return_value=0) as mock_cmd,
      patch("sys.argv", ["yoker-test", "show", "--suite", "my_suite"]),
      patch("sys.exit") as mock_exit,
    ):
      main()
      mock_cmd.assert_called_once_with("my_suite")
      mock_exit.assert_called_once_with(0)

  def test_show_missing_suite_arg_exits(self):
    with (
      patch("sys.argv", ["yoker-test", "show"]),
      pytest.raises(SystemExit) as exc_info,
    ):
      main()
    assert exc_info.value.code == 2


class TestBackwardCompat:
  """Tests for backward-compatible --model flag."""

  def test_model_redirects_to_eval(self):
    """--model without subcommand redirects to eval with yoker_basic suite."""
    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch("sys.argv", ["yoker-test", "--model", "gpt-4"]),
      patch("sys.exit"),
    ):
      main()
      mock_cmd.assert_called_once_with("yoker_basic", "gpt-4", None, None, None, verbose=False)

  def test_no_args_prints_help_and_exits(self, capsys):
    with (
      patch("sys.argv", ["yoker-test"]),
      pytest.raises(SystemExit) as exc_info,
    ):
      main()
    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "usage:" in output.lower()

  def test_legacy_default_model_not_used(self):
    """Without --model and without subcommand, should not call asyncio.run."""
    with (
      patch("yoker_test.cli.asyncio.run") as mock_run,
      patch("sys.argv", ["yoker-test"]),
      pytest.raises(SystemExit),
    ):
      main()
      mock_run.assert_not_called()


class TestCmdEval:
  """Tests for cmd_eval handler."""

  async def test_success_returns_zero(self, capsys):
    mock_report = _mock_report()
    with patch("yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report):
      ret = await cmd_eval("my_suite", "gpt-4", None, None, None)
    assert ret == 0
    output = capsys.readouterr().out
    assert "Suite:" in output
    assert "Model:" in output

  async def test_suite_not_found_returns_one(self, capsys):
    with patch(
      "yoker_test.cli.evaluate",
      new_callable=AsyncMock,
      side_effect=FileNotFoundError("Suite not found: missing"),
    ):
      ret = await cmd_eval("missing", "gpt-4", None, None, None)
    assert ret == 1
    err = capsys.readouterr().err
    assert "Suite not found" in err

  async def test_validation_failure_returns_one(self, capsys):
    with patch(
      "yoker_test.cli.evaluate",
      new_callable=AsyncMock,
      side_effect=ValueError("Suite validation failed: bad config"),
    ):
      ret = await cmd_eval("bad", "gpt-4", None, None, None)
    assert ret == 1
    err = capsys.readouterr().err
    assert "Suite validation failed" in err

  async def test_output_yaml(self, tmp_path, capsys):
    mock_report = _mock_report()
    output_file = tmp_path / "results.yaml"
    with patch("yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report):
      ret = await cmd_eval("my_suite", "gpt-4", None, str(output_file), None)
    assert ret == 0
    assert output_file.exists()
    content = output_file.read_text()
    assert "test_suite" in content
    output = capsys.readouterr().out
    assert "Report saved" in output

  async def test_output_json(self, tmp_path, capsys):
    mock_report = _mock_report()
    output_file = tmp_path / "results.json"
    with patch("yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report):
      ret = await cmd_eval("my_suite", "gpt-4", None, str(output_file), None)
    assert ret == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["run"]["suite"] == "test_suite"

  async def test_repeats_passed_through(self):
    mock_report = _mock_report()
    with patch(
      "yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report
    ) as mock_ev:
      await cmd_eval("my_suite", "gpt-4", None, None, repeats=5)
      mock_ev.assert_called_once_with(suite="my_suite", model="gpt-4", compare=None, repeats=5)

  async def test_compare_passed_through(self):
    mock_report = _mock_report()
    with patch(
      "yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report
    ) as mock_ev:
      await cmd_eval("my_suite", "gpt-4", "baseline.yaml", None, None)
      mock_ev.assert_called_once_with(
        suite="my_suite", model="gpt-4", compare="baseline.yaml", repeats=None
      )


class TestVerboseFlag:
  """Tests for --verbose wiring on eval and the legacy --model path."""

  def test_eval_verbose_flag_parses(self):
    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch("sys.argv", ["yoker-test", "eval", "--suite", "my_suite", "--verbose"]),
      patch("sys.exit"),
    ):
      main()
      assert mock_cmd.call_args.args[-1] is True

  def test_legacy_model_verbose_flag(self):
    """--model X --verbose dispatches with verbose=True via legacy_verbose dest."""
    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch("sys.argv", ["yoker-test", "--model", "gpt-4", "--verbose"]),
      patch("sys.exit"),
    ):
      main()
      assert mock_cmd.call_args.kwargs["verbose"] is True

  def test_default_verbose_false_both_paths(self):
    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch("sys.argv", ["yoker-test", "eval", "--suite", "my_suite"]),
      patch("sys.exit"),
    ):
      main()
      assert mock_cmd.call_args.args[-1] is False

  def test_subparser_default_does_not_clobber(self):
    """Legacy --model --verbose followed by eval subcommand: the eval parser's
    --verbose default must not reset the flag (dest-collision regression)."""
    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch("sys.argv", ["yoker-test", "--verbose", "--model", "gpt-4"]),
      patch("sys.exit"),
    ):
      main()
      assert mock_cmd.call_args.kwargs["verbose"] is True

  async def test_cmd_eval_passes_per_test_detail_when_verbose(self, capsys):
    mock_report = _mock_report()
    with (
      patch("yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report),
      patch("yoker_test.cli.format_console_report", return_value="") as mock_fmt,
    ):
      await cmd_eval("my_suite", "gpt-4", None, None, None, verbose=True)
      mock_fmt.assert_called_once_with(mock_report, per_test_detail=True)

  async def test_cmd_eval_default_no_per_test_detail(self, capsys):
    mock_report = _mock_report()
    with (
      patch("yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report),
      patch("yoker_test.cli.format_console_report", return_value="") as mock_fmt,
    ):
      await cmd_eval("my_suite", "gpt-4", None, None, None)
      mock_fmt.assert_called_once_with(mock_report, per_test_detail=False)


class TestCmdSuites:
  """Tests for cmd_suites handler."""

  def test_no_suites_dir(self, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ret = cmd_suites()
    assert ret == 0
    output = capsys.readouterr().out
    assert "No suites/" in output

  def test_empty_suites_dir(self, capsys, tmp_path, monkeypatch):
    (tmp_path / "suites").mkdir()
    monkeypatch.chdir(tmp_path)
    ret = cmd_suites()
    assert ret == 0
    output = capsys.readouterr().out
    assert "No suites found" in output

  def test_one_suite(self, capsys, tmp_path, monkeypatch):
    suite_dir = tmp_path / "suites" / "my_suite"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
      "suite: my_suite\nversion: '1.0'\ndescription: Test\n"
      "tasks:\n"
      "  - id: T1\n    category: math\n    prompt: 1+1\n    expected: '2'\n    scorer: mcq\n",
      encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    ret = cmd_suites()
    assert ret == 0
    output = capsys.readouterr().out
    assert "my_suite" in output
    assert "1.0" in output

  def test_multiple_suites(self, capsys, tmp_path, monkeypatch):
    for name in ["alpha", "beta"]:
      d = tmp_path / "suites" / name
      d.mkdir(parents=True)
      (d / "suite.yaml").write_text(
        f"suite: {name}\nversion: '1.0'\ndescription: {name} suite\n"
        "tasks:\n"
        "  - id: T1\n    category: math\n    prompt: 1+1\n    expected: '2'\n    scorer: mcq\n",
        encoding="utf-8",
      )
    monkeypatch.chdir(tmp_path)
    ret = cmd_suites()
    assert ret == 0
    output = capsys.readouterr().out
    assert "alpha" in output
    assert "beta" in output

  def test_dir_without_suite_yaml_skipped(self, capsys, tmp_path, monkeypatch):
    suite_dir = tmp_path / "suites" / "real"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
      "suite: real\nversion: '1.0'\ndescription: Real\n"
      "tasks:\n"
      "  - id: T1\n    category: math\n    prompt: 1+1\n    expected: '2'\n    scorer: mcq\n",
      encoding="utf-8",
    )
    (tmp_path / "suites" / "empty").mkdir()
    monkeypatch.chdir(tmp_path)
    ret = cmd_suites()
    assert ret == 0
    output = capsys.readouterr().out
    assert "real" in output
    assert "empty" not in output


class TestCmdShow:
  """Tests for cmd_show handler."""

  def test_valid_suite(self, capsys, tmp_path, monkeypatch):
    suite_dir = tmp_path / "suites" / "my_suite"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
      "suite: my_suite\nversion: '1.0'\ndescription: Test suite\n"
      "repeats: 5\ntemperature: 0.3\nseed: 99\nmax_tokens: 4096\n"
      "tasks:\n"
      "  - id: T1\n    category: math\n    prompt: 1+1\n    expected: '2'\n    scorer: mcq\n    difficulty: easy\n"
      "  - id: T2\n    category: logic\n    prompt: true?\n    expected: 'true'\n    scorer: mcq\n",
      encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    ret = cmd_show("my_suite")
    assert ret == 0
    output = capsys.readouterr().out
    assert "my_suite" in output
    assert "1.0" in output
    assert "5" in output
    assert "[math]" in output
    assert "[logic]" in output
    assert "4096" in output

  def test_not_found_returns_one(self, capsys):
    ret = cmd_show("nonexistent")
    assert ret == 1
    err = capsys.readouterr().err
    assert "Error:" in err

  def test_invalid_suite_returns_one(self, capsys, tmp_path, monkeypatch):
    suite_dir = tmp_path / "suites" / "bad"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
      "suite: bad\nversion: '1.0'\ndescription: Bad\n"
      "tasks:\n"
      "  - id: T1\n    category: math\n    prompt: 1+1\n    expected: '2'\n    scorer: nonexistent_scorer\n",
      encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    ret = cmd_show("bad")
    assert ret == 1
    err = capsys.readouterr().err
    assert "Validation errors" in err

  def test_tasks_grouped_by_category(self, capsys, tmp_path, monkeypatch):
    suite_dir = tmp_path / "suites" / "grouped"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
      "suite: grouped\nversion: '1.0'\ndescription: Grouped\n"
      "tasks:\n"
      "  - id: M1\n    category: math\n    prompt: q\n    expected: a\n    scorer: mcq\n"
      "  - id: M2\n    category: math\n    prompt: q2\n    expected: a2\n    scorer: mcq\n"
      "  - id: L1\n    category: logic\n    prompt: q3\n    expected: a3\n    scorer: mcq\n",
      encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    ret = cmd_show("grouped")
    assert ret == 0
    output = capsys.readouterr().out
    assert "[math] (2 tasks)" in output
    assert "[logic] (1 tasks)" in output

  def test_aggregation_weights_displayed(self, capsys, tmp_path, monkeypatch):
    suite_dir = tmp_path / "suites" / "weighted"
    suite_dir.mkdir(parents=True)
    (suite_dir / "suite.yaml").write_text(
      "suite: weighted\nversion: '1.0'\ndescription: Weighted\n"
      "aggregation:\n  weights:\n    math: 0.6\n    logic: 0.4\n"
      "tasks:\n"
      "  - id: M1\n    category: math\n    prompt: q\n    expected: a\n    scorer: mcq\n"
      "  - id: L1\n    category: logic\n    prompt: q2\n    expected: a2\n    scorer: mcq\n",
      encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    ret = cmd_show("weighted")
    assert ret == 0
    output = capsys.readouterr().out
    assert "Aggregation Weights" in output
    assert "math" in output
    assert "0.60" in output


class TestLegacyRemovals:
  """Tests verifying old code was removed."""

  def test_async_main_not_importable(self):
    """async_main should no longer exist in cli module."""
    import yoker_test.cli as cli

    assert not hasattr(cli, "async_main")

  def test_old_imports_removed(self):
    """Legacy imports should no longer be present."""
    import yoker_test.cli as cli

    assert not hasattr(cli, "run_single_test")
    assert not hasattr(cli, "fetch_ollama_usage")
    assert not hasattr(cli, "print_report")
    assert not hasattr(cli, "TestTask")
