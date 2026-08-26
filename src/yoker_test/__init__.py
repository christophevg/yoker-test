"""yoker-test: A model evaluation framework for Yoker.

Tests LLM models through Yoker's actual backend pipeline, producing
multi-dimensional profiles (quality + efficiency: tokens, latency, cost).
"""

__version__ = "0.1.0"
__author__ = "Christophe VG"

from yoker_test.config import TestConfig, evaluate
from yoker_test.report import ComparisonReport
from yoker_test.runner import EvalRunner
from yoker_test.schema import Score, SuiteConfig, TestReport, TestTask

__all__ = [
  "__version__",
  "__author__",
  # Public API
  "evaluate",
  # Config
  "TestConfig",
  # Runner
  "EvalRunner",
  # Schema
  "TestTask",
  "TestReport",
  "Score",
  "SuiteConfig",
  # Report
  "ComparisonReport",
]
