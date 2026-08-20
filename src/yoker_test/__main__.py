#!/usr/bin/env python3
"""yoker-test main entry point.

Runs a hardcoded MCQ task through Yoker's SDK, scores it, and prints
multi-dimensional metrics (quality, efficiency, cost).

Usage:
  yoker-test --model glm-5.2:cloud
"""

from yoker_test.cli import main

if __name__ == "__main__":
  main()
