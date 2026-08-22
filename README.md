# yoker-test

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://docs.astral.sh/uv)
[![CI](https://img.shields.io/github/actions/workflow/status/christophevg/yoker-test/test.yml)](https://github.com/christophevg/yoker-test/actions/workflows/test.yml)
[![License](https://img.shields.io/github/license/christophevg/yoker-test.svg)](https://github.com/christophevg/yoker-test/blob/master/LICENSE)
[![workflow: agentic](https://img.shields.io/badge/workflow-agentic-blueviolet?style=flat-square)](https://christophe.vg/about/Agentic-Workflow)

> A model evaluation framework for [Yoker](https://github.com/christophevg/yoker) — tests LLM models through Yoker's actual backend pipeline, producing multi-dimensional profiles: quality (correctness), efficiency (tokens, latency), and cost (API usage).

## Quick Start

```bash
uv sync
make run
```

## How to Use

```bash
# Run with the default model
make run

# Run with a specific model
make run MODEL=gpt-oss:20b-cloud

# Run directly
uv run yoker-test --model glm-5.2:cloud
```

## Testing

```bash
make test
```

## Development

```bash
# Install all dependencies (dev + docs)
uv sync --all-extras

# Run all quality checks
make check

# Build documentation
make docs

# Build package
make build
```

## Status

Pre-alpha. Under active development.

## License

MIT — see [LICENSE](LICENSE)