"""Scorers for yoker-test: score model responses against expected answers."""

import re
from collections.abc import Callable

from yoker_test.schema import TestTask


def mcq_scorer(task: TestTask, response: str) -> tuple[float, str | None]:
  """Extract A-D from response, compare to expected. Returns (score, extracted)."""
  text = response.strip()

  # 1. Response is exactly one of A/B/C/D
  if text in ("A", "B", "C", "D"):
    return (1.0 if text == task.expected else 0.0, text)

  # 2. "Answer: B" pattern
  m = re.search(r"(?i)Answer[ \t]*:[ \t]*\$?([A-D])\$?", text)
  if m:
    letter = m.group(1).upper()
    return (1.0 if letter == task.expected else 0.0, letter)

  # 3. First standalone A/B/C/D
  m = re.search(r"\b([ABCD])\b", text)
  if m:
    letter = m.group(1).upper()
    return (1.0 if letter == task.expected else 0.0, letter)

  # 4. "B) Paris" pattern
  m = re.match(r"^([ABCD])\)", text)
  if m:
    letter = m.group(1).upper()
    return (1.0 if letter == task.expected else 0.0, letter)

  return (0.0, None)


SCORERS: dict[str, Callable[[TestTask, str], tuple[float, str | None]]] = {
  "mcq": mcq_scorer,
}
