# yoker-test

A model evaluation framework for [Yoker](https://github.com/christophevg/yoker).

Tests LLM models through Yoker's actual backend pipeline, producing
multi-dimensional profiles (quality + efficiency: tokens, latency, cost).

## Status

Pre-alpha. Under active development.

## Usage

```bash
yoker-test --model glm-5.2:cloud
```

## Development

```bash
make run MODEL=glm-5.2:cloud
```