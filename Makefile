YOKER_FROM = ../yoker
-include ~/.yoker/Makefile

YOKER_TEST = uv run yoker-test

MODEL ?= glm-5.2:cloud

.PHONY: env-dev env-run install-pythons test test-cov test-file format lint typecheck format-check check run size clean clean-all help

## Environment

env-dev: ## Install all dependencies (dev)
	uv sync --all-extras

env-run: ## Install runtime dependencies only
	uv sync

install-pythons: ## Install Python 3.10, 3.11, 3.12
	uv python install 3.10 3.11 3.12

## Testing

test: env-dev ## Run tests (usage: make test / optional: TEST=file|file:test_name)
	uv run --extra dev pytest -v $(TEST)

test-cov: env-dev ## Run tests with coverage
	uv run --extra dev pytest --cov=src --cov-report=term-missing

test-file: env-dev ## Run a single test file (usage: make test-file TEST=tests/test_schema.py)
	uv run --extra dev pytest -v $(TEST)

## Code Quality

format: env-dev ## Format code and fix linting issues
	uv run --extra dev ruff format src tests
	uv run --extra dev ruff check --fix src tests

lint: env-dev ## Check code for linting issues
	uv run --extra dev ruff check src tests

typecheck: env-dev ## Run type checking
	uv run --extra dev mypy src

format-check: format lint typecheck ## Run all quality checks

check: format-check test ## Run all quality checks and tests

size:
	@echo "src/"
	@find src/ | grep "\.py$$" | xargs wc -l | sort -rn | head -10
	@echo "tests/"
	@find tests/ | grep "\.py$$" | xargs wc -l | sort -rn | head -10

## Running

run: env-run ## Run yoker-test (usage: make run / optional: MODEL=gpt-4)
	$(YOKER_TEST) --model $(MODEL) 2>&1

## Cleanup

clean: ## Remove build artifacts and caches
	rm -rf dist/ build/ *.egg-info .pytest_cache .coverage .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Remove virtualenv and lock file
	rm -rf .venv uv.lock
