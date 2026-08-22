# API Reference

## yoker_test.loader

### load_suite(path: str | Path) -> SuiteConfig

Load a test suite from a YAML file.

### validate_suite(config: SuiteConfig) -> list[str]

Validate a loaded suite configuration. Returns list of error strings (empty = valid).

## yoker_test.schema

### TestTask

A single test task with prompt, expected answer, and scorer.

### SuiteConfig

A complete test suite configuration with tasks and metadata.

### TestReport

A complete test report with results and summaries.