"""Custom scorers for the yoker_basic suite."""

import re

from yoker_test.schema import Score, TestTask


def count_bullet_lines(task: TestTask, response: str) -> float:
  """Score based on the number of bullet-point lines in the response.

  Expected (task.expected) is the target count.
  Score = min(actual_count, expected) / expected.
  """
  expected_count = int(task.expected)
  lines = response.strip().split("\n")
  bullet_lines = [line for line in lines if re.match(r"^\s*[-*]\s+", line)]
  actual_count = len(bullet_lines)
  if expected_count == 0:
    return 1.0 if actual_count == 0 else 0.0
  return min(actual_count, expected_count) / expected_count


def tool_call_verify(task: TestTask, response: str) -> Score:
  """Verify that the response contains a valid tool call.

  Expected (task.expected) is a dict with 'tool' and 'args'.
  Returns a Score with sub_scores for each check.
  """
  expected = task.expected if isinstance(task.expected, dict) else {}
  expected_tool = expected.get("tool", "")
  expected_args = expected.get("args", [])

  sub_scores: dict[str, float] = {}

  sub_scores["tool_name"] = 1.0 if expected_tool.lower() in response.lower() else 0.0

  args_found = all(str(a).lower() in response.lower() for a in expected_args)
  sub_scores["args_present"] = 1.0 if args_found else 0.0

  # Check if response looks like a tool call (JSON or function-call format)
  looks_like_call = bool(
    re.search(r'\{.*["\'](?:tool|function|name)["\'].*\}', response, re.IGNORECASE)
  )
  sub_scores["format"] = 1.0 if looks_like_call else 0.0

  value = sum(sub_scores.values()) / len(sub_scores) if sub_scores else 0.0
  return Score(
    value=value,
    sub_scores=sub_scores,
    explanation=f"tool={expected_tool}, args={expected_args}",
  )