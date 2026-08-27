"""Dynamic task generators for the yoker_basic suite."""

import random

from yoker_test.schema import TestTask


def generate_math_problem(config: dict) -> TestTask:
  """Generate a random arithmetic problem.

  Config keys: seed, min_val, max_val.
  """
  rng = random.Random(config.get("seed", 42))
  a = rng.randint(config.get("min_val", 10), config.get("max_val", 99))
  b = rng.randint(config.get("min_val", 10), config.get("max_val", 99))
  return TestTask(
    id=f"R_DYN_{a}_{b}",
    category="reasoning",
    difficulty="medium",
    prompt=f"What is {a} * {b}? Answer with just the number.",
    expected=a * b,
    scorer="numeric_match",
    scorer_config={"tolerance": 0.01},
  )


def generate_logic_puzzle(config: dict) -> TestTask:
  """Generate a random logic puzzle.

  Config keys: seed.
  """
  rng = random.Random(config.get("seed", 43))
  people = ["Alice", "Bob", "Carol", "Dave"]
  rng.shuffle(people)
  line = people[:3]
  # Ask about someone who isn't last, so there's always a valid answer
  ask_index = rng.randint(0, 1)
  ask_person = line[ask_index]
  answer = line[ask_index + 1]

  return TestTask(
    id=f"R_DYN_LOGIC_{config.get('seed', 43)}",
    category="reasoning",
    difficulty="hard",
    prompt=(
      f"Three people are standing in a line: {line[0]}, {line[1]}, and {line[2]}. "
      f"Who is standing immediately after {ask_person}? "
      f"Answer with just the name."
    ),
    expected=answer,
    scorer="exact_match",
    scorer_config={"ignore_case": True},
  )


def generate_dynamic_tasks(config: dict) -> list[TestTask]:
  """Produce 2+ dynamic tasks for the yoker_basic suite."""
  base_seed = config.get("seed", 42)
  return [
    generate_math_problem({"seed": base_seed}),
    generate_logic_puzzle({"seed": base_seed + 1}),
  ]