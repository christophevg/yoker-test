"""Tests for P2.9: loader merge behavior, --with flag, subprocess code execution,
custom scorers, dynamic generators, and full suite loading."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from yoker_test.loader import load_suite, validate_suite
from yoker_test.schema import Score, TestTask
from yoker_test.scorers import code_execution

SUITE_DIR = Path(__file__).parent.parent / "suites" / "yoker_basic"


# --- Loader merge behavior ---


class TestLoaderMerge:
  """Tests for static + dynamic task merge in load_suite."""

  def test_static_and_generator_merged(self, tmp_path):
    """Static tasks + task_generator output are merged, not replaced."""
    yaml_content = """
suite: merge_test
version: "1.0"
description: "Merge test"
tasks:
  - id: STATIC1
    category: c
    prompt: "static"
    expected: "A"
    scorer: mcq
task_generator: !function tests.test_p2_9._gen_two_tasks
"""
    path = tmp_path / "suite.yaml"
    path.write_text(yaml_content)
    config = load_suite(path)
    assert len(config.tasks) == 3
    assert config.tasks[0].id == "STATIC1"
    assert config.tasks[1].id == "DYN0"
    assert config.tasks[2].id == "DYN1"

  def test_static_only_no_generator(self, tmp_path):
    """Static tasks work without a generator."""
    yaml_content = """
suite: static_only
version: "1.0"
description: "Static only"
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "A"
    scorer: mcq
"""
    path = tmp_path / "suite.yaml"
    path.write_text(yaml_content)
    config = load_suite(path)
    assert len(config.tasks) == 1
    assert config.tasks[0].id == "T1"

  def test_generator_only_no_static(self, tmp_path):
    """Generator works without static tasks."""
    yaml_content = """
suite: gen_only
version: "1.0"
description: "Gen only"
task_generator: !function tests.test_p2_9._gen_two_tasks
"""
    path = tmp_path / "suite.yaml"
    path.write_text(yaml_content)
    config = load_suite(path)
    assert len(config.tasks) == 2

  def test_suite_dir_added_to_sys_path(self, tmp_path):
    """load_suite adds the suite's directory to sys.path."""
    yaml_content = """
suite: path_test
version: "1.0"
description: "Path test"
tasks:
  - id: T1
    category: c
    prompt: "?"
    expected: "A"
    scorer: mcq
"""
    path = tmp_path / "suite.yaml"
    path.write_text(yaml_content)
    load_suite(path)
    assert str(tmp_path.resolve()) in sys.path


# --- --with flag ---


class TestWithFlag:
  """Tests for the --with CLI flag."""

  def test_with_flag_adds_path(self):
    """--with adds a directory to sys.path before loading."""
    from yoker_test.cli import main

    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch(
        "sys.argv",
        ["yoker-test", "eval", "--suite", "my_suite", "--with", "/some/path"],
      ),
      patch("sys.exit"),
    ):
      main()
      mock_cmd.assert_called_once_with(
        "my_suite", "glm-5.2:cloud", None, None, None, ["/some/path"], False
      )

  def test_with_flag_multiple(self):
    """--with can be specified multiple times."""
    from yoker_test.cli import main

    with (
      patch("yoker_test.cli.cmd_eval", new_callable=AsyncMock, return_value=0) as mock_cmd,
      patch("yoker_test.cli.asyncio.run", side_effect=lambda coro: coro),
      patch(
        "sys.argv",
        ["yoker-test", "eval", "--suite", "my_suite", "--with", "/a", "--with", "/b"],
      ),
      patch("sys.exit"),
    ):
      main()
      mock_cmd.assert_called_once_with(
        "my_suite", "glm-5.2:cloud", None, None, None, ["/a", "/b"], False
      )

  async def test_cmd_eval_adds_with_paths_to_sys_path(self):
    """cmd_eval adds --with paths to sys.path."""
    from yoker_test.cli import cmd_eval

    test_path = "/tmp/test_with_path_xyz"
    mock_report = type("MockReport", (), {"to_json": lambda s: "{}", "to_yaml": lambda s: ""})()
    with (
      patch("yoker_test.cli.evaluate", new_callable=AsyncMock, return_value=mock_report),
      patch("yoker_test.cli.format_console_report", return_value="report"),
    ):
      await cmd_eval("my_suite", "model", None, None, None, [test_path])
      assert test_path in sys.path
      sys.path.remove(test_path)


# --- Subprocess code execution ---


class TestCodeExecutionSubprocess:
  """Tests for the subprocess-based code_execution scorer."""

  def test_correct_solution(self):
    code = "def solution(a, b):\n  return a + b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
          {"func": "solution", "args": [5, 5], "expected": 10},
        ]
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 1.0
    assert result.sub_scores == {"case_0": 1.0, "case_1": 1.0}

  def test_partial_correct(self):
    code = "def solution(a, b):\n  return a + b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
          {"func": "solution", "args": [5, 5], "expected": 11},
        ]
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 0.5
    assert result.sub_scores == {"case_0": 1.0, "case_1": 0.0}

  def test_no_code_found(self):
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={"test_cases": [{"func": "solution", "args": [], "expected": 1}]},
    )
    assert code_execution(task, "") == 0.0

  def test_no_test_cases(self):
    task = TestTask(id="C1", category="code", prompt="?", expected="", scorer="code_execution")
    code = "def solution():\n  return 1"
    assert code_execution(task, code) == 0.0

  def test_exec_error(self):
    code = "def solution(a, b):\n  return a / b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 0], "expected": None},
        ]
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 0.0
    assert result.sub_scores == {"case_0": 0.0}

  def test_func_not_found(self):
    code = "def wrong_name(a, b):\n  return a + b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [
          {"func": "solution", "args": [1, 2], "expected": 3},
        ]
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 0.0

  def test_timeout(self):
    """Code that runs too long is killed and scores 0."""
    code = "import time\ndef solution():\n  time.sleep(10)\n  return 1"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "timeout": 2,
        "test_cases": [{"func": "solution", "args": [], "expected": 1}],
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 0.0

  def test_plain_code_fence(self):
    code = "def solution(a, b):\n  return a + b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [{"func": "solution", "args": [1, 2], "expected": 3}],
      },
    )
    result = code_execution(task, f"```\n{code}\n```")
    assert isinstance(result, Score)
    assert result.value == 1.0

  def test_raw_code_no_fence(self):
    code = "def solution(a, b):\n  return a + b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [{"func": "solution", "args": [1, 2], "expected": 3}],
      },
    )
    result = code_execution(task, code)
    assert isinstance(result, Score)
    assert result.value == 1.0

  def test_explanation_in_result(self):
    code = "def solution(a, b):\n  return a + b"
    task = TestTask(
      id="C1",
      category="code",
      prompt="?",
      expected="",
      scorer="code_execution",
      scorer_config={
        "test_cases": [{"func": "solution", "args": [1, 2], "expected": 3}],
      },
    )
    result = code_execution(task, f"```python\n{code}\n```")
    assert isinstance(result, Score)
    assert result.explanation == "1/1 cases passed"


# --- Custom scorers ---


class TestCountBulletLines:
  """Tests for count_bullet_lines suite-local scorer."""

  def test_exact_count(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=3, scorer="custom")
    response = "- Apple\n- Banana\n- Cherry"
    assert count_bullet_lines(task, response) == 1.0

  def test_partial_count(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=5, scorer="custom")
    response = "- Apple\n- Banana\n- Cherry"
    assert count_bullet_lines(task, response) == 0.6

  def test_zero_expected(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=0, scorer="custom")
    assert count_bullet_lines(task, "- item") == 0.0

  def test_zero_expected_zero_bullets(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=0, scorer="custom")
    assert count_bullet_lines(task, "no bullets here") == 1.0

  def test_asterisk_bullets(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=2, scorer="custom")
    response = "* Red\n* Blue"
    assert count_bullet_lines(task, response) == 1.0

  def test_mixed_bullets(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=3, scorer="custom")
    response = "- One\n* Two\n- Three"
    assert count_bullet_lines(task, response) == 1.0

  def test_no_bullets(self):
    from suites.yoker_basic.scorers import count_bullet_lines

    task = TestTask(id="I1", category="instruction", prompt="?", expected=3, scorer="custom")
    assert count_bullet_lines(task, "just text") == 0.0


class TestToolCallVerify:
  """Tests for tool_call_verify suite-local scorer."""

  def test_full_match(self):
    from suites.yoker_basic.scorers import tool_call_verify

    task = TestTask(
      id="T1",
      category="tool_use",
      prompt="?",
      expected={"tool": "calculator", "args": ["17", "*", "23"]},
      scorer="custom",
    )
    response = '{"tool": "calculator", "args": ["17", "*", "23"]}'
    result = tool_call_verify(task, response)
    assert isinstance(result, Score)
    assert result.value == 1.0
    assert result.sub_scores == {
      "tool_name": 1.0,
      "args_present": 1.0,
      "format": 1.0,
    }

  def test_tool_name_present_args_missing(self):
    from suites.yoker_basic.scorers import tool_call_verify

    task = TestTask(
      id="T1",
      category="tool_use",
      prompt="?",
      expected={"tool": "calculator", "args": ["17", "*", "23"]},
      scorer="custom",
    )
    response = '{"tool": "calculator"}'
    result = tool_call_verify(task, response)
    assert isinstance(result, Score)
    assert result.sub_scores["tool_name"] == 1.0
    assert result.sub_scores["args_present"] == 0.0

  def test_no_tool_name(self):
    from suites.yoker_basic.scorers import tool_call_verify

    task = TestTask(
      id="T1",
      category="tool_use",
      prompt="?",
      expected={"tool": "weather", "args": ["Tokyo"]},
      scorer="custom",
    )
    # Tool name missing, only args present, no JSON format
    response = "The conditions in Tokyo are sunny today."
    result = tool_call_verify(task, response)
    assert isinstance(result, Score)
    assert result.sub_scores["tool_name"] == 0.0
    assert result.sub_scores["args_present"] == 1.0

  def test_partial_score(self):
    from suites.yoker_basic.scorers import tool_call_verify

    task = TestTask(
      id="T1",
      category="tool_use",
      prompt="?",
      expected={"tool": "search", "args": ["Python", "asyncio", "tutorial"]},
      scorer="custom",
    )
    # Tool name missing, only 2 of 3 args present, no JSON format
    response = "Search for Python asyncio"
    result = tool_call_verify(task, response)
    assert isinstance(result, Score)
    assert 0.0 < result.value < 1.0


# --- Dynamic generators ---


class TestGenerators:
  """Tests for dynamic task generators."""

  def test_generate_math_problem(self):
    from suites.yoker_basic.generators import generate_math_problem

    task = generate_math_problem({"seed": 42, "min_val": 10, "max_val": 99})
    assert task.category == "reasoning"
    assert task.scorer == "numeric_match"
    assert "*" in task.prompt
    assert isinstance(task.expected, int)
    assert task.id.startswith("R_DYN_")

  def test_generate_math_problem_deterministic(self):
    """Same seed produces same task."""
    from suites.yoker_basic.generators import generate_math_problem

    t1 = generate_math_problem({"seed": 42})
    t2 = generate_math_problem({"seed": 42})
    assert t1.id == t2.id
    assert t1.expected == t2.expected

  def test_generate_logic_puzzle(self):
    from suites.yoker_basic.generators import generate_logic_puzzle

    task = generate_logic_puzzle({"seed": 43})
    assert task.category == "reasoning"
    assert task.difficulty == "hard"
    assert task.scorer == "exact_match"
    assert task.id.startswith("R_DYN_LOGIC_")

  def test_generate_dynamic_tasks_returns_list(self):
    from suites.yoker_basic.generators import generate_dynamic_tasks

    tasks = generate_dynamic_tasks({"seed": 42})
    assert isinstance(tasks, list)
    assert len(tasks) == 2
    assert all(isinstance(t, TestTask) for t in tasks)
    assert all(t.category == "reasoning" for t in tasks)


# --- Full suite loading ---


class TestFullSuiteLoad:
  """Tests for loading the complete yoker_basic suite."""

  def test_suite_loads_with_30_tasks(self):
    """Full suite loads with 30 tasks (28 static + 2 dynamic)."""
    config = load_suite(SUITE_DIR / "suite.yaml")
    assert len(config.tasks) == 30

  def test_suite_validates_clean(self):
    """Full suite passes validation."""
    config = load_suite(SUITE_DIR / "suite.yaml")
    errors = validate_suite(config)
    assert errors == []

  def test_category_counts(self):
    """Correct category distribution: 8/8/6/4/4."""
    config = load_suite(SUITE_DIR / "suite.yaml")
    cats: dict[str, int] = {}
    for t in config.tasks:
      cats[t.category] = cats.get(t.category, 0) + 1
    assert cats == {"knowledge": 8, "reasoning": 8, "instruction": 6, "code": 4, "tool_use": 4}

  def test_dynamic_tasks_in_suite(self):
    """Suite contains 2 dynamic tasks from the generator."""
    config = load_suite(SUITE_DIR / "suite.yaml")
    dynamic = [t for t in config.tasks if t.id.startswith("R_DYN_")]
    assert len(dynamic) == 2

  def test_all_ids_unique(self):
    """All task IDs are unique across static + dynamic."""
    config = load_suite(SUITE_DIR / "suite.yaml")
    ids = [t.id for t in config.tasks]
    assert len(ids) == len(set(ids))


# --- Helper functions for tests ---


def _gen_two_tasks(config: dict) -> list[TestTask]:
  """Generate 2 simple test tasks for merge tests."""
  return [
    TestTask(
      id=f"DYN{i}",
      category="generated",
      prompt=f"Question {i}",
      expected="A",
      scorer="mcq",
    )
    for i in range(2)
  ]
