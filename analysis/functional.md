# Functional Analysis: yoker-test

> Based on `yoker-test-analysis.md` and `yoker-split-analysis.md` design
> documents, the existing codebase, and project configuration.

## 1. Project Purpose and Scope

**yoker-test** is a standalone Python package that provides a testing
framework for evaluating LLM models running through Yoker. It answers two
complementary questions:

1. **How well does a model run in Yoker?** — Model quality (correctness,
   reasoning, instruction following) measured through Yoker's actual backend
   pipeline.
2. **How well does Yoker run a model?** — By comparing scores across Yoker
   versions with the same model and suite, score changes become an indirect
   regression test for Yoker itself.

The output is a **multi-dimensional model profile** — not just "how smart is
this model?" but "how efficient is it?", "what does it cost?", and "did Yoker's
changes affect its performance?" — compiled into a landscape overview of models
and how they perform in Yoker.

### 1.0 Primary Goal (Owner Priority)

> **The main goal right now**: A report containing all Ollama cloud models
> with their ranking by "quality for usage". The cost factor is Ollama
> session/weekly usage % (already collected by `usage.py`), NOT token-based
> pricing computation (which is deferred — see FR10 and section 11).

This means the first deliverable is:
1. Build the suite runner with multi-scorer support
2. Run it against all Ollama cloud models
3. Produce a quality ranking report with usage % as the cost factor

Token-based pricing (per-model `input_per_million`/`output_per_million`) is
deferred until API models with real per-token costs need to be compared.

### 1.1 Positioning

yoker-test is **not** another LLM benchmark framework. It does not aim to
compete with lm-evaluation-harness, lighteval, or Inspect AI. It is
purpose-built for the Yoker ecosystem:

- Tests run **through Yoker's actual backend layer** (`process()`,
  `Agent.process()`, or `backend.chat_stream()`), not a standalone inference
  pipeline.
- Results are **comparable across Yoker versions** — same model, same suite,
  different Yoker version → delta = Yoker's change.
- Efficiency metrics (tokens, latency, cost) are **first-class** alongside
  quality scores.
- The framework is **configuration-driven** — test suites are YAML + optional
  Python, the runtime is a small generic engine (~300-400 lines).

### 1.2 The Bidirectional Loop

```
                    yoker-test eval
                        │
           ┌────────────┴────────────┐
           ▼                         ▼
    Model Profiles              Score Deltas
    (quality + efficiency)      (regression signal)
           │                         │
           ▼                         ▼
  docs/model-compatibility.md   Bug reports / fixes in Yoker
           │                         │
           ▼                         ▼
  Users choose models         Yoker improves
           │                         │
           └────────────┬────────────┘
                        │
                        ▼
                  Re-run yoker-test
                  (with better Yoker)
```

### 1.3 The unittest Analogy

The architecture maps directly to Python's `unittest`:

| unittest | yoker-test |
|---|---|
| `TestRunner` | `EvalRunner` |
| `TestCase` / `test_*` methods | `TestTask` |
| `assertEqual(a, b)` | `scorer(task, response) → float` |
| `setUp` / `tearDown` | runtime config (temp=0, seed, repeats) |
| `TestSuite` | suite YAML |
| test discovery | suite loading (parse YAML, resolve `!function`) |
| pass/fail (boolean) | score 0.0–1.0 (graded) |
| test report | eval report (per-task, per-category, overall, with stats) |
| — | baseline comparison (regression detection) |

### 1.4 Scope Boundaries

**In scope:**
- Test suite definition (YAML format with dynamic task generation via `!function`)
- Multi-scorer support (mcq, exact_match, numeric_match, regex_extract,
  contains, json_valid, code_execution) + custom scorers via `!function`
- Suite execution through Yoker's SDK with metric collection
- Multi-turn conversation support (sequential turns, full message exchange)
- Category-level and overall reporting with multi-dimensional metrics
- Baseline comparison for regression detection
- CLI interface (`eval`, `suites`, `show` subcommands)
- Quality ranking report across all Ollama cloud models (primary deliverable)
- Cost factor: Ollama session/weekly usage % (NOT token-based pricing — deferred)
- Python public API (`evaluate()`, `EvalRunner`)
- Landscape overview generation (model compatibility table)

**Deferred (per owner decision):**
- Token-based pricing computation (`pricing.py` module, `input_per_million`/
  `output_per_million` per model). Will be revisited when API models with real
  per-token costs need to be compared.

**Out of scope:**
- Yoker's own backend implementation (we use it, not modify it — except Phase 3)
- Model training or fine-tuning
- Web UI or dashboard (CLI-only for now)
- Distributed/parallel test execution
- Competing with external benchmark frameworks (MMLU, GSM8K, etc.)
- LLM-as-judge (future Phase 4, not in current scope)

## 2. Architecture: Framework vs. Configuration

The core design principle is **strict separation** between the test runtime
framework (HOW to test) and the test suite configuration (WHAT to test).

```
Framework (runtime):  HOW to test    — send prompt, collect response, gather stats, aggregate
Configuration (suite): WHAT to test  — which prompts, how to score, what categories
```

The framework is a generic execution engine. It knows nothing about math
questions, multiple choice, or code generation. It only knows: "take a
prompt, send it to a model through Yoker, get a response back, apply a scoring
function, record everything."

The configuration brings the domain knowledge: the actual prompts, the
expected answers, the scoring logic. It can be as simple as a YAML file with
static tasks, or as rich as a Python module with dynamic task generation and
custom scorers.

### 2.1 Framework Core — What It Owns

1. **Loading a configuration** — Parse YAML suite definition, resolve
   `!function` references to Python callables, validate well-formedness.
2. **Executing tests through Yoker** — For each task, send the prompt through
   `process()` or `backend.chat_stream()`. Collect response text, `UsageStats`
   (tokens, latency). Handle repeats and errors.
3. **Applying scorers** — Look up scorer by name (built-in) or use the provided
   callable (custom). Call `scorer(task, response) → float | Score`.
4. **Aggregating results** — Group by category, compute mean ± std, sum
   tokens/latency, compute cost, produce structured report.
5. **Baseline comparison (optional)** — Load a previous report, compute deltas
   per category and overall, flag regressions.
6. **Report output** — Serialize to YAML/JSON, optional human-readable summary.

The framework is deliberately ~300-400 lines of Python. It is a loop with
bookkeeping.

### 2.2 Configuration — What It Brings

```
Suite Definition
├── Metadata: name, version, description
├── Runtime: temperature, seed, repeats, max_tokens
├── Tasks: the actual test cases
│   ├── Static: defined inline in YAML
│   └── Dynamic: generated by a Python function
├── Scorers: how to evaluate responses
│   ├── Built-in: referenced by name (exact_match, numeric_match, ...)
│   └── Custom: Python callables loaded from a module
└── Aggregation: how to combine scores (optional weights per category)
```

### 2.3 The Interface — Three Protocols

```python
# A task is what the framework executes
@dataclass
class TestTask:
    id: str
    category: str
    difficulty: str
    prompt: str
    expected: Any           # whatever the scorer needs
    scorer: str | Callable   # name of built-in, or a callable
    scorer_config: dict      # kwargs passed to the scorer
    system_prompt: str | None = None

# A scorer evaluates a response — returns a float or a richer Score
Scorer = Callable[[TestTask, str], float | Score]

# A task generator produces tasks dynamically
TaskGenerator = Callable[[dict], list[TestTask]]
```

The framework only needs these three things. Everything else is configuration.

### 2.4 What the Framework Does NOT Do

- No prompt engineering — prompts come from the suite config
- No answer interpretation — the scorer handles that, scorers come from config
- No dataset loading — if a suite needs external data, the task generator handles it
- No model selection — the caller specifies the model
- No benchmark comparison — it doesn't compare to MMLU or GSM8K scores
- No statistical significance testing — it reports mean ± std, the caller decides
- No LLM-as-judge — that's a custom scorer the suite config would provide

## 3. Functional Requirements

### FR1: Test Task Definition
The system must define test tasks with: unique ID, category, difficulty, prompt,
expected answer (Any type), scorer (name or callable), scorer config, and
optional system prompt.

### FR2: Multi-Scorer Support
The system must support multiple scoring strategies, each extracting and
comparing model responses against expected answers:
- **mcq** — Multiple choice (A-D extraction with 6-stage fallback)
- **exact_match** — Normalize and compare strings, config: `ignore_case`,
  `ignore_punctuation`
- **numeric_match** — Extract first number, compare with tolerance, config:
  `tolerance`
- **regex_extract** — Apply regex, compare captured group, config: `pattern`,
  `group`
- **contains** — Check if expected string appears in response, config:
  `ignore_case`
- **json_valid** — Parse JSON, optionally check keys, config: `required_keys`
- **code_execution** — Extract code, exec in sandbox, run test cases, config:
  `test_cases`, `timeout`
- **Custom scorers** — Python callables loaded via `!function` YAML tags

### FR3: Suite Format and Loading
The system must load test suites from YAML files with:
- Suite-level metadata: `suite` (name), `version`, `description`
- Runtime config: `repeats`, `temperature`, `seed`
- Task definitions (static inline + dynamic via `!function` tags)
- Optional `task_generator` with `generator_config` for dynamic suites
- Optional `scorers` section for per-suite scorer config
- Optional `aggregation.weights` for category weighting
- Suite validation (required fields, scorer existence, ID uniqueness)

### FR4: Suite Execution
The system must execute test suites through Yoker's SDK via three paths:
- `yoker.process()` — one-shot for standard tasks (no tools)
- `yoker.agent()` — for tool-use tasks requiring an agent with tools
- `backend.chat_stream()` — for direct backend access (full control)
- Support multiple repeats per task (default: 3 for statistical reliability)
- Handle per-task errors gracefully (record error, score 0.0, continue suite)
- Collect `UsageStats` (tokens, latency) from Yoker's event stream
- Support multi-turn conversations: tasks with `turns` field send messages
  sequentially, collecting the full message exchange in `TestResult.messages`

### FR5: Metric Collection
The system must collect per-task metrics:
- **Tokens**: `input_tokens`/`output_tokens` (OpenAI/Anthropic) with fallback
  to `prompt_eval_count`/`eval_count` (Ollama) — nullable
- **Latency**: `total_duration_ms` (backend-reported) with wall-clock fallback
- **TTFT**: time to first token (if streaming) — nullable
- **Character split**: thinking vs content chunks from event stream
- **Cost**: Ollama API usage delta (session/weekly) when available

### FR6: Scoring and Composite
The system must compute:
- Per-task score (0.0–1.0) via the configured scorer
- Category-level aggregation (mean ± std, avg tokens, avg latency, total cost)
- Overall quality score (weighted by category, weights from config or uniform)
- Composite score: `quality × cost_score` where
  `cost_score = 1 / (1 + cost_per_correct × scale)`
  - Free models → cost_score = 1.0 → composite = quality
  - Quality is the floor — wrong answers can't be "cheap enough"

### FR7: Report Generation
The system must produce reports with:
- **Run metadata**: suite name, suite version, model, provider, yoker version,
  temperature, seed, repeats, timestamp
- **Per-task results**: all repeats, with score, response, tokens, latency,
  scorer name, extracted answer, sub_scores (if any)
- **Category summaries**: score, std, n_tasks, avg_tokens_in, avg_tokens_out,
  avg_latency_ms, total_tokens, total_latency_s, cost
- **Overall summary**: score, std, total_tokens_in, total_tokens_out,
  total_tokens, total_latency_s, avg_tokens_per_second, total_cost,
  cost_per_correct_answer
- **Baseline comparison** (optional): per-category and overall deltas, flagged
  regressions
- Serialization to YAML, JSON, and dict

### FR8: Regression Detection
The system must support regression testing:
- Store baseline results keyed by (Yoker version, model, suite version)
- Compare new runs against stored baseline
- Report per-category and overall deltas
- Flag regressions where `|delta| > 2 × std` (configurable threshold)
- Prefer Ollama (local) models for baselines — only truly deterministic option

### FR9: CLI Interface
The system must provide a CLI with subcommands:
- `eval` — Run a suite against a model, output results
- `suites` — List available suites
- `show` — Display suite contents without running
- Flags: `--suite`, `--model`, `--compare`, `--output`, `--repeats`

### FR10: Pricing and Cost (DEFERRED per owner decision)
> **Deferred**: Token-based pricing computation is deferred. The cost factor
> for now is Ollama session/weekly usage % (already collected by `usage.py`).
> The primary goal is a quality ranking report across all Ollama cloud models.
> Will be revisited when API models with real per-token costs need comparison.

The system should eventually compute costs from token counts:
- Load pricing data from external YAML file (maintained separately from suites)
- Pricing format: `input_per_million`, `output_per_million` per model
- Compute: `cost = (tokens_in × input_price + tokens_out × output_price) / 1_000_000`
- Compute `cost_per_correct_answer = total_cost / (overall_score × n_tasks)`
- Ollama (local) models → cost = 0.0 (free compute)

**Current cost approach (active)**: Use Ollama session/weekly usage % delta
as the cost factor. This is already implemented in `usage.py` and
`report.py` (`compute_composite` with `cost_delta`).

### FR11: Python Public API
The system must provide a Python API:
- `evaluate(suite, model, compare=None)` — simple one-call interface
- `EvalRunner(tasks, repeats, temperature)` — programmatic suite construction
- `TestReport` with `.to_yaml()`, `.to_json()`, `.to_dict()` methods

### FR12: Landscape Overview
The system must support generating a model compatibility overview:
- Aggregate results across multiple models
- Produce a compatibility table (quality, efficiency, tool use, cost, recommendations)
- Output as Markdown for documentation (e.g., `docs/model-compatibility.md`)

### FR13: Backend Integration (Three Execution Paths)
The system must support three execution paths through Yoker's SDK,
selected based on task requirements:

- **`yoker.process()`** — one-shot prompt → response for standard tasks
  (no tools, no system prompt by default). Used for knowledge, reasoning,
  instruction, and code tasks.
- **`yoker.agent()`** — for tool-use tasks requiring an agent with specific
  tools enabled. Inspect the agent's event stream for `ToolCallDelta`
  events to verify tool invocation and argument parsing.
- **`backend.chat_stream()`** — for direct backend access when full control
  is needed (e.g., custom event handling, streaming metrics). Collects
  `ChatChunkEvent.CONTENT_DELTA` for response text and
  `ChatChunkEvent.USAGE` for token counts.

The runner must normalize `UsageStats` across providers:

```python
tokens_in = usage.input_tokens or usage.prompt_eval_count or 0
tokens_out = usage.output_tokens or usage.eval_count or 0
latency_ms = usage.total_duration_ms or wall_clock_ms
```

`UsageStats` fields are provider-neutral:
- `input_tokens` / `output_tokens` — OpenAI/Anthropic
- `prompt_eval_count` / `eval_count` — Ollama native (== input/output tokens)
- `total_duration_ms` — Ollama native total duration

### FR14: Baseline Registry
The system must maintain a baseline registry for regression comparison:
- Store baseline results keyed by (Yoker version, model, suite version)
- Registry format: YAML file (`baselines/registry.yaml`) with entries
  containing `yoker_version`, `suite_version`, `model`, quality/efficiency/
  composite scores, timestamp, and optional `delta_from_previous`
- Load and match baselines by (yoker_version, suite_version, model)
- Support a "latest" baseline reference for quick comparison

### FR15: Reference Model Set
The system should define a fixed reference model set for regression
baselines, covering the main backend paths:
- One small Ollama model (e.g., `llama3.2:3b`) — fast, cheap, local,
  deterministic
- One larger Ollama model (e.g., `llama3.1:8b`) — more capable, still local
- One API model (e.g., `gpt-4o-mini`) — different backend path (LiteLLM)

If all three show the same delta, it's clearly Yoker, not a model fluke.
Prefer Ollama models for regression baselines — only truly deterministic
option (local execution, no silent model updates, no batch non-determinism).

### FR16: Model Refusal Handling
The system must handle models that refuse to answer:
- Record as error, score 0.0
- Flag in report as "refused" if detected (safety filter triggers,
  empty/nonsensical response patterns)
- Continue suite execution (don't abort)

### FR17: Statistical Rigor
The system must provide statistically rigorous reporting:
- Run each task N=3 times (Blackwell et al. 2024: sufficient for prediction
  interval < 0.01 with temp=0)
- Report mean ± std per category and overall, not single point estimates
- Support bootstrap confidence intervals (as lm-eval does by default)
- For baseline comparison, flag deltas where |delta| > 2 × std as real
  regressions
- Consider dual-filter reporting for numeric extraction (strict + flexible)
  so consumers can see the extraction gap

### FR18: Multi-Turn Conversation Support
The system must support multi-turn test/task scenarios to create complex
enough tests to differentiate between models:
- Tasks can define a `turns` field: a list of `{"role": "user"/"assistant",
  "content": "..."}` messages sent sequentially
- The runner sends each turn through Yoker, collects model responses, and
  builds the full `messages` list in `TestResult`
- Scorers can access the full conversation (last response or full exchange)
- Single-turn tasks (with `prompt` field) work unchanged — backward compatible
- Multi-turn enables testing: context retention, instruction chaining,
  reasoning across turns, tool-use in conversation context
- The suite YAML format supports both `prompt` (single-turn) and `turns`
  (multi-turn) task definitions

## 4. Key Data Structures and Relationships

### 4.1 Current (Phase 1 — implemented)

```
TestTask                    TestResult
├── id: str                 ├── task_id: str
├── category: str           ├── category: str
├── prompt: str             ├── score: float
├── expected: str           ├── response: str
├── scorer: str             ├── extracted: str | None
└── scorer_config: dict     ├── tokens_in: int
                            ├── tokens_out: int
                            ├── latency_ms: float
                            ├── thinking_chars: int
                            ├── content_chars: int
                            └── error: str | None
```

**Relationship**: One `TestTask` → one `TestResult` per execution.
`run_single_test(task, config) → TestResult`.

### 4.2 Target (Phase 2 — from design doc)

#### TestTask (extended)

```python
@dataclass
class TestTask:
    id: str
    category: str          # e.g. "knowledge", "reasoning", "code"
    difficulty: str        # "easy", "medium", "hard"
    prompt: str            # what to send to the model
    expected: Any          # what the scorer compares against
    scorer: str | Callable # built-in name or custom callable
    scorer_config: dict    # kwargs for the scorer
    system_prompt: str | None = None  # optional per-task system prompt
```

#### Score (scorer return type)

A scorer can return a bare float or a richer `Score` object:

```python
@dataclass
class Score:
    value: float                    # 0.0 - 1.0, the primary score
    extracted: str | None = None    # what was extracted from the response
    sub_scores: dict[str, float] | None = None  # e.g. per-test-case results
    explanation: str | None = None  # why this score (for debugging)
```

Simple scorers return `1.0`. Code execution scorers return
`Score(value=0.75, sub_scores={"test_1": 1.0, "test_2": 0.0})`. The framework
unpacks the `Score` into the `TestResult` fields.

#### TestResult (extended)

```python
@dataclass
class TestResult:
    # Identity
    task_id: str
    category: str
    difficulty: str
    repeat: int               # which repetition (0-indexed)

    # The exchange
    prompt: str               # what was sent
    response: str             # what came back
    messages: list[dict]      # full message exchange (if multi-turn)

    # Quantitative metrics (from Yoker's UsageStats + wall-clock)
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float         # total time, prompt to completion
    ttft_ms: float | None    # time to first token (if streaming)

    # Quality (from the scorer)
    score: float              # 0.0 - 1.0
    scorer_name: str
    extracted: str | None     # what the scorer extracted
    sub_scores: dict[str, float] | None

    # Status
    error: str | None         # if the call failed
```

The framework collects everything except `score`, `scorer_name`, `extracted`,
`sub_scores`, and `error` automatically. The scorer adds the quality dimension.
Errors are caught by the framework.

#### RunMetadata

```python
@dataclass
class RunMetadata:
    suite: str
    suite_version: str
    model: str
    provider: str
    yoker_version: str
    temperature: float
    seed: int
    repeats: int
    timestamp: str
```

#### CategorySummary

```python
@dataclass
class CategorySummary:
    score: float           # mean score
    std: float             # standard deviation
    n_tasks: int
    avg_tokens_in: float
    avg_tokens_out: float
    avg_latency_ms: float
    total_tokens: int
    total_latency_s: float
```

#### OverallSummary

```python
@dataclass
class OverallSummary:
    score: float
    std: float
    total_tokens_in: int
    total_tokens_out: int
    total_tokens: int
    total_latency_s: float
    avg_tokens_per_second: float
    usage_delta: dict[str, float] | None  # Ollama session/weekly % delta
    # NOTE: total_cost and cost_per_correct_answer are deferred (FR10).
    # For now, usage_delta serves as the cost factor.
```

#### TestReport

```python
@dataclass
class TestReport:
    run: RunMetadata
    results: list[TestResult]
    summary: dict[str, CategorySummary]  # keyed by category
    overall: OverallSummary
    comparison: ComparisonReport | None

    def to_yaml(self) -> str: ...
    def to_json(self) -> str: ...
    def to_dict(self) -> dict: ...
```

#### ComparisonReport

```python
@dataclass
class ComparisonReport:
    baseline: RunMetadata
    delta: dict[str, float]     # per-category + "overall"
    flagged: list[str]          # categories where |delta| > 2 × std
```

### 4.3 Relationships

- `SuiteConfig` contains task definitions (static + dynamic via `!function`)
  and runtime config (repeats, temperature, seed)
- `EvalRunner` executes all `TestTask`s, producing `TestResult`s (one per
  task × repeat)
- `TestReport` aggregates `TestResult`s into `CategorySummary` (per category)
  and `OverallSummary` (weighted across categories)
- `ComparisonReport` compares a current `TestReport` against a stored baseline
- `RunMetadata` captures the execution context for reproducibility
- `Score` is the rich return type from scorers, unpacked into `TestResult`

## 5. Scoring System Design

### 5.1 Scorer Interface

```python
Scorer = Callable[[TestTask, str], float | Score]
```

Each scorer receives the task and the model's response, returns a float
(0.0–1.0) or a richer `Score` object. The framework unpacks `Score` into
`TestResult` fields.

### 5.2 Scorer Registry

```python
SCORERS: dict[str, Scorer] = {
  "mcq": mcq_scorer,
  "exact_match": exact_match,
  "numeric_match": numeric_match,
  "regex_extract": regex_extract,
  "contains": contains,
  "json_valid": json_valid,
  "code_execution": code_execution,
}
```

Custom scorers are loaded via `!function` YAML tags — same interface.

### 5.3 Answer Normalization

Adopted from OpenAI's `simple-evals` `normalize_response` function — strip
markdown and LaTeX formatting before comparison:

```python
def normalize_response(response: str) -> str:
    return (
        response.replace("**", "")
        .replace("$\\boxed{", "")
        .replace("}$", "")
        .replace("\\$", "")
        .replace("$\\text{", "")
        .replace("$", "")
        .replace("\\mathrm{", "")
        .replace("\\{", "")
        .replace("\\text", "")
        .replace("\\(", "")
        .replace("\\mathbf{", "")
        .replace("{", "")
        .replace("\\boxed", "")
    )
```

### 5.4 MCQ Answer Extraction (6-stage fallback)

Multi-step fallback chain (first match wins), based on patterns observed in
major frameworks:

```
1. Response is exactly one of A/B/C/D → use it
2. Regex: r'(?i)Answer[ \t]*:[ \t]*\$?([A-D])\$?' → use it
3. Regex: r'\b([ABCD])\b' on first line → use it
4. Regex: r'^([ABCD])\)' → use it (e.g., "B) Paris")
5. First standalone A/B/C/D in the response → use it
6. No match → score 0
```

### 5.5 Numeric Answer Extraction

```
1. Strip all non-numeric characters except . and -
2. Extract the first number (regex: r'-?[\d.]+')
3. Handle common formats: "36", "36.0", "$36", "36 degrees"
4. Convert to float
5. Compare with tolerance
```

### 5.6 Code Extraction

```
1. If ```python ... ``` in response → extract content between fences
2. If ``` ... ``` → extract content
3. Otherwise → use entire response (strip whitespace)
4. Exec in sandbox with timeout
5. Run test cases, score = cases_passed / total_cases
```

### 5.7 Built-in Scorers Summary

| Name | What It Does | Config |
|---|---|---|
| `exact_match` | Normalize both strings, compare | `ignore_case`, `ignore_punctuation` |
| `numeric_match` | Extract first number from response, compare with tolerance | `tolerance` |
| `regex_extract` | Apply regex, compare captured group | `pattern`, `group` |
| `contains` | Check if expected string appears in response | `ignore_case` |
| `mcq` | Extract letter A-D from response, compare | — |
| `json_valid` | Try `json.loads()`, optionally check keys | `required_keys` |
| `code_execution` | Extract code, exec in sandbox, run test cases | `test_cases`, `timeout` |

### 5.8 Custom Scorers

For domain-specific scoring, the configuration provides Python functions:

**In YAML (lm-eval style with `!function`):**
```yaml
tasks:
  - id: X1
    prompt: "..."
    expected: "some complex thing"
    scorer: !function my_suite.scorers.evaluate_x1
```

**In Python (direct):**
```python
suite = Suite(
    tasks=[
        TestTask(id="X1", prompt="...", expected="...", scorer=my_scorer),
    ]
)
```

The framework doesn't care. A scorer is a callable that takes
`(task, response)` and returns a float or `Score`. Whether it's a built-in
name, a `!function` reference, or a direct callable — same interface.

## 6. Suite Format and Loading

### 6.1 Simple Case — Static Tasks, Built-in Scorers

```yaml
suite: yoker_basic
version: "1.0"
description: "Minimal model evaluation suite for Yoker"
repeats: 3
temperature: 0.0
seed: 42

tasks:
  - id: K1
    category: knowledge
    difficulty: easy
    prompt: |
      Question: What is the chemical symbol for gold?
      A) Gd  B) Go  C) Au  D) Ag
      Reply with only the letter.
    expected: "C"
    scorer: mcq

  - id: R1
    category: reasoning
    difficulty: easy
    prompt: "What is 15% of 240? Answer with just the number."
    expected: 36
    scorer: numeric_match
    scorer_config:
      tolerance: 0.01

  - id: I1
    category: instruction
    difficulty: easy
    prompt: "List exactly 3 fruits. Each on a new line prefixed with '- '."
    expected: 3
    scorer: !function yoker_basic.scorers.count_bullet_lines
```

### 6.2 Rich Case — Dynamic Generation, Custom Scorers

```yaml
suite: yoker_code_eval
version: "1.0"
repeats: 1
temperature: 0.0

task_generator: !function code_suite.generate_tasks
generator_config:
  difficulty: [easy, medium, hard]
  count: 20

scorers:
  code_execution:
    timeout: 5
    sandbox: restricted

aggregation:
  weights:
    easy: 0.2
    medium: 0.3
    hard: 0.5
```

### 6.3 The `!function` Resolution Mechanism

Similar to lm-eval-harness's `!function` operator. The loader resolves
`!function module.path.function` by importing the module and retrieving the
attribute. This allows suites to provide custom Python code (scorers,
generators) alongside their YAML configuration.

The resolution happens at suite load time, before any tests are executed.
If a function can't be resolved, the load fails with a clear error.

### 6.4 Loader Responsibilities

1. Parse YAML with custom `!function` tag handler
2. Resolve function references to Python callables (import module, get attribute)
3. If `task_generator` present: call it with `generator_config` → get tasks
4. Else: use static tasks from YAML
5. For each task: resolve scorer (built-in name → function, or use callable)
6. Validate: required fields present, scorer names exist in `SCORERS`, task IDs
   unique
7. Return `SuiteConfig` with all tasks expanded

### 6.5 Dynamic Task Generation

`!function` tags reference Python functions that generate task content at
load time. This enables:
- Parameterized tasks (e.g., random math problems)
- Tasks derived from external data sources
- Tasks with computed expected answers
- `TaskGenerator = Callable[[dict], list[TestTask]]`

## 7. Report Format and Output

### 7.1 Full Report (YAML)

```yaml
run:
  suite: yoker_basic
  suite_version: "1.0"
  model: llama3.2:3b
  provider: ollama
  yoker_version: 0.10.1
  temperature: 0.0
  seed: 42
  repeats: 3
  timestamp: 2025-01-15T10:30:00Z

results:
  - task_id: K1
    category: knowledge
    difficulty: easy
    repeat: 0
    score: 1.0
    response: "C"
    tokens_in: 42
    tokens_out: 3
    latency_ms: 850
    scorer: mcq
    extracted: "C"
  - task_id: K1
    repeat: 1
    score: 1.0
    ...
  - task_id: R1
    category: reasoning
    repeat: 0
    score: 1.0
    response: "150"
    tokens_in: 28
    tokens_out: 5
    latency_ms: 1200
    scorer: numeric_match
    extracted: "150"
  ...

summary:
  knowledge:
    score: 0.875
    std: 0.0
    n_tasks: 8
    avg_tokens_in: 40
    avg_tokens_out: 4
    avg_latency_ms: 900
    total_tokens: 1080
    total_latency_s: 20.4
    cost: 0.0
  reasoning:
    score: 0.625
    std: 0.05
    n_tasks: 8
    avg_tokens_in: 65
    avg_tokens_out: 120
    avg_latency_ms: 2800
    total_tokens: 7800
    total_latency_s: 67.2
    cost: 0.0
  instruction:
    score: 0.583
    std: 0.03
    n_tasks: 6
    ...
  code:
    score: 0.250
    std: 0.08
    n_tasks: 4
    ...
  tool_use:
    score: 0.250
    std: 0.06
    n_tasks: 4
    ...

overall:
  score: 0.536
  std: 0.02
  total_tokens_in: 4200
  total_tokens_out: 1800
  total_tokens: 6000
  total_latency_s: 112.5
  avg_tokens_per_second: 16.0
  total_cost: 0.0
  cost_per_correct_answer: 0.0

# Only present if --compare was given
comparison:
  baseline:
    yoker_version: 0.9.0
    timestamp: 2025-01-10T08:00:00Z
  delta:
    knowledge: 0.0       # stable
    reasoning: -0.125    # regression! investigate
    instruction: +0.04   # improvement
    code: +0.0
    tool_use: -0.25      # regression! tool parsing may be broken
    overall: -0.03
  flagged: [reasoning, tool_use]  # |delta| > 2 × std
```

### 7.2 Console Report (Current — single task, Phase 1)

```
yoker-test — model: glm-5.2:cloud

  Task:   K1 (knowledge)
  Prompt: Question: What is the chemical symbol for gold?...

──────────────────────────────────────────────────
  Score:      1.0
  Response:   'C'
  Extracted:  'C'
  Expected:   'C'
  Tokens in:  42
  Tokens out: 3
  Thinking:   150 chars (60%)
  Content:    100 chars (40%)
  Latency:    1234 ms
  Session:    10.0000% → 10.0010% (+0.0010%)
  Weekly:     50.0000% → 50.0010% (+0.0010%)
  Composite:  0.9091
──────────────────────────────────────────────────
```

### 7.3 Machine-Readable Output

`--output results.yaml` or `--output results.json` produces a serialized
`TestReport` structure. `TestReport` provides `.to_yaml()`, `.to_json()`, and
`.to_dict()` methods for programmatic consumption and baseline storage.

### 7.4 Landscape Overview

Aggregated across multiple models, the report can be compiled into a
compatibility table for documentation:

```markdown
# Yoker Model Compatibility

## Ollama Models

| Model | Quality | Efficiency | Tool Use | Cost | Recommended For |
|-------|---------|------------|---------|------|----------------|
| llama3.2:3b | ★★★☆☆ | ★★★★★ | ✅ | free | Simple tasks, local |
| llama3.1:8b | ★★★★☆ | ★★★★☆ | ✅ | free | General purpose, local |

## API Models

| Model | Quality | Efficiency | Tool Use | Cost/Eval |
|-------|---------|------------|---------|----------|
| gpt-4o-mini | ★★★★☆ | ★★★★☆ | ✅ | $0.02 |
| gpt-4o | ★★★★★ | ★★★☆☆ | ✅ | $0.15 |
```

This document is both the output of the eval system and the input for Yoker's
documentation. When a new model is released, run `yoker-test eval`, generate a
profile, and update the compatibility table.

## 8. Regression Testing Capability

### 8.1 The Differential Approach

```
Yoker v1.0  +  Model X  +  Suite A  →  Score S1
Yoker v1.1  +  Model X  +  Suite A  →  Score S2

Δ = S2 - S1  →  indirect measure of Yoker's change
```

The model is the **fixed reference**. The suite is the **fixed probe**.
Yoker is the **variable**. Any score change is attributable to Yoker because
nothing else moved.

### 8.2 What the Delta Captures

| Dimension | If it drops, Yoker might have... | If it improves, Yoker might have... |
|---|---|---|
| Quality | Changed prompt formatting, broken system prompt handling, altered context construction, introduced a bug in tool calling | Improved prompt construction, better context handling, fixed a tool-call parsing bug |
| Latency | Added processing overhead, broken streaming efficiency | Optimized the processing pipeline, improved streaming |
| Token usage | Changed how context is built (adding/removing tokens), altered system prompt injection | Tightened context construction, reduced overhead tokens |
| Tool-use score | Broken tool argument parsing, changed tool schema generation | Fixed tool parsing, improved schema format for models |

### 8.3 Stored Baselines

Each eval run produces a result bundle keyed by (Yoker version, model, suite
version). These are stored. Next time, load the matching baseline and compute
deltas.

```yaml
# baselines/registry.yaml
- yoker_version: "1.0.0"
  suite_version: "1.0"
  model: llama3.2:3b
  quality: 0.66
  efficiency: 0.85
  composite: 0.72
  timestamp: 2025-01-10

- yoker_version: "1.1.0"
  suite_version: "1.0"
  model: llama3.2:3b
  quality: 0.64
  efficiency: 0.83
  composite: 0.69
  timestamp: 2025-01-20
  delta_from_previous:
    quality: -0.02
    efficiency: -0.02
    composite: -0.03
```

### 8.4 Reference Model Set

A small, fixed set of models that cover the main backend paths:

- One small Ollama model (e.g., `llama3.2:3b`) — fast, cheap, local, deterministic
- One larger Ollama model (e.g., `llama3.1:8b`) — more capable, still local
- One API model (e.g., `gpt-4o-mini`) — different backend path (LiteLLM)

If all three show the same delta, it's clearly Yoker, not a model fluke.

**Prefer Ollama models for regression baselines** — they're the only ones that
are truly deterministic (local execution, no silent model updates, no batch
non-determinism). API models can silently update, making baselines unreliable
over time.

### 8.5 Practical Workflow

```
Developer changes Yoker code
  → make check (existing tests pass)
  → yoker-test eval --model llama3.2:3b --suite yoker_basic
  → compare to stored baseline
  → if |delta| > threshold: investigate / fix / update baseline
  → if |delta| ≤ threshold: commit, baseline becomes new reference
```

Could be a Makefile target or CI step:

```makefile
eval-regression: ## Run model evaluation and compare to baseline
	uv run yoker-test eval --model llama3.2:3b --suite yoker_basic --compare baselines/latest.yaml
```

### 8.6 Noise Floor

With 30 graded prompts, the noise floor is roughly ±2-3 points (based on
graded scoring giving ~120 distinct score combinations). Changes of 3+ points
are likely real. With 3 repeats per task, the prediction interval width is
typically < 0.01 (Blackwell et al. 2024).

### 8.7 Regression Flagging

Regressions are flagged when `|delta| > 2 × std` — not a fixed threshold. This
accounts for categories with higher variance naturally. The `flagged` list in
the comparison report contains category names that exceed this threshold.

## 9. Reliability

### 9.1 Sources of Non-Determinism

Research (Coqueret et al. 2026, Biderman et al. 2024, Blackwell et al. 2024,
Tamba 2026) identifies five sources of non-determinism even at temperature=0:

| Source | Survives T=0? | Controllable? |
|---|---|---|
| Deliberate sampling | No | Yes (set T=0) |
| Silent model updates | Yes | Only with local models |
| Floating-point rounding (batch size, hardware) | Yes | Only with local execution |
| Expert routing (MoE models) | Yes | Partially (local execution) |
| Server load / hardware differences | Yes | Only with local execution |

**Key finding**: Only local execution of open-weight models (e.g., Ollama)
gives fully deterministic results. API models will always have residual
non-determinism.

**Key finding**: Some newer models (Claude Opus 4.7/4.8) have deprecated
temperature entirely — the primary mitigation is being removed by providers.
The only robust mitigation that survives is statistical: run epochs > 1 and
report variance.

### 9.2 Mitigations

| Risk | Mitigation |
|---|---|
| Answer extraction failure | Multi-step extraction pipeline with fallback regexes, tested against real model outputs |
| Numeric edge cases | Tolerance-based comparison, handle multiple valid answers |
| Code extraction failure | Multiple fence format handling, fallback to raw response |
| Model non-determinism | Temperature=0, fixed seed, run N=3 repeats, report mean ± std |
| Suite contamination | Mix of standard questions + custom phrasings; version the suite |
| Scorer bugs | Unit-test the scorers against known model output samples |
| Prompt sensitivity | Fixed prompt template, no/fixed system prompt, same for all runs |
| API model silent updates | Prefer Ollama models for baselines; record model version + date |
| Borderline item flips | Inherent — report variance, don't treat as bugs |

### 9.3 Statistical Reporting

- Run each task **3 times** (Blackwell et al. show this is sufficient for
  prediction interval < 0.01 with temp=0)
- Report **mean ± std** per category and overall, not single point estimates
- For baseline comparison, flag deltas where **|delta| > 2 × std** as real
  regressions
- Adopt **bootstrap confidence intervals** (as lm-eval does by default)

### 9.4 Prompt Sensitivity

Biderman et al. (2024) document:
- Prompt formatting alone can change scores by **>20%** on the same model
- Different implementations of MMLU produce **different scores AND different
  model rankings**
- Single-run point estimates are misleading — GPQA scores for frontier models
  overlap significantly when 95% CIs are computed over 10 runs

**Implication**: Freeze prompts. Never change them without bumping the suite
version. Baselines are only comparable within the same suite version.

### 9.5 Answer Extraction

Biderman et al.: "different models may generate responses in varying formats,
making it challenging to create a universal regex pattern that works for all
models."

lm-eval-harness uses **dual filter pipelines** for GSM8K:
- `strict-match`: regex `"The answer is (\\-?[0-9\\.\\,]+)"` → take first
- `flexible-extract`: regex `"(-?[$0-9.,]{2,})|(-?[0-9]+)"` → take last

**Implication**: Our multi-step extraction pipeline with fallbacks is the right
approach. Consider reporting both strict and flexible scores so consumers can
see the gap.

## 10. Module Structure and Responsibilities

### 10.1 Current Modules (Phase 1 — Complete)

| Module | Responsibility | Key Exports |
|--------|---------------|-------------|
| `schema.py` | Core dataclasses | `TestTask`, `TestResult` |
| `scorers.py` | Scoring functions + registry | `mcq_scorer`, `SCORERS` |
| `usage.py` | Ollama API usage fetching | `fetch_ollama_usage` |
| `runner.py` | Test execution + metric collection | `StatsCollector`, `run_single_test` |
| `report.py` | Composite scoring + report formatting | `compute_composite`, `print_report` |
| `cli.py` | CLI entry point + orchestration | `main`, `async_main` |
| `__main__.py` | Thin entry point | — |

### 10.2 Target Modules (Phase 2 — from design doc)

```
yoker-test/
├── src/yoker_test/
│   ├── __init__.py         # Public API: evaluate(), EvalRunner, TestTask, TestReport, Score
│   ├── schema.py           # TestTask, TestResult, TestReport, SuiteConfig, Score, RunMetadata
│   ├── runner.py           # EvalRunner — the execution loop (~200-300 lines)
│   ├── scorers.py          # Built-in scorers (mcq, exact_match, numeric_match, ...)
│   ├── loader.py           # Load suite YAML, resolve !function references
│   ├── report.py           # Aggregate results, format report, compare baselines
│   ├── config.py           # TestConfig (extends yoker.Config)
│   ├── cli.py              # yoker-test CLI (thin wrapper around runner)
│   # pricing.py            # DEFERRED — token-based pricing (see FR10)
│   # usage.py              # Existing — Ollama usage % (current cost factor)
├── suites/                  # Built-in test suites (configuration, not framework code)
│   └── yoker_basic/
│       ├── suite.yaml       # Task definitions + metadata (single-turn + multi-turn)
│       ├── scorers.py       # Custom scorers (optional)
│       └── generators.py    # Custom task generators (optional)
├── baselines/               # Stored baselines for regression comparison
│   └── registry.yaml
└── tests/                   # Tests for the framework itself
```

### 10.3 Module Responsibilities

| Module | Responsibility | Key Exports |
|--------|---------------|-------------|
| `schema.py` | All dataclasses | `TestTask`, `TestResult`, `Score`, `TestReport`, `SuiteConfig`, `RunMetadata`, `CategorySummary`, `OverallSummary`, `ComparisonReport` |
| `scorers.py` | All scorers + normalize utility | `mcq_scorer`, `exact_match`, `numeric_match`, `regex_extract`, `contains`, `json_valid`, `code_execution`, `normalize_response`, `SCORERS` |
| `loader.py` | Suite YAML loading + validation | `load_suite`, `validate_suite` |
| `runner.py` | Suite execution engine | `StatsCollector`, `EvalRunner`, `run_single_test` |
| `report.py` | Aggregation + serialization | `compute_composite`, `aggregate_results`, `compare_baseline`, `format_console_report`, `format_quality_ranking`, `serialize_report` |
| ~~`pricing.py`~~ | ~~Pricing data + cost computation~~ | ~~DEFERRED — see FR10~~ |
| `config.py` | Test config (extends yoker.Config) | `TestConfig` |
| `cli.py` | Full CLI with subcommands | `main`, `cmd_eval`, `cmd_suites`, `cmd_show` |
| `__init__.py` | Public API | `evaluate`, `EvalRunner`, `TestTask`, `TestReport`, `Score` |
| `__main__.py` | Thin entry point | — |

### 10.4 Relationship to Yoker

```
yoker (SDK)                      yoker-test (package)
├── process()                    ├── evaluate()
├── Agent.process()              ├── EvalRunner
├── backend.chat_stream()        │   └── uses process() or backend
├── UsageStats                   ├── TestTask / TestResult / TestReport
└── Config                       └── SuiteConfig
```

yoker-test depends on yoker as a Python SDK. It uses:
- `yoker.process()` — one-shot prompt → response (no tools, no system prompt)
- `yoker.Agent` — for tool-use tasks that need an agent with tools
- `yoker.backends.protocol.UsageStats` — for token/latency collection
- `yoker.Config` — for model/provider configuration

yoker-test does NOT depend on Yoker's CLI, UI, session management, or plugin
system. It uses the SDK layer only.

### 10.5 Key Design Decision: Standalone Package

yoker-test is a **standalone package** with a dependency on yoker (as SDK),
not a submodule of yoker. This is because:

1. **Separation of concerns** — yoker is an agent harness; yoker-test is a test
   framework. Different audiences, different release cycles.
2. **yoker stays lean** — the eval framework is not needed by most yoker users.
3. **Independent versioning** — yoker-test can release independently of yoker.
4. **Third-party suites** — someone could write a domain-specific eval suite
   and run it through yoker-test without modifying either yoker or yoker-test.

### 10.6 Backend Integration: Three Execution Paths

The eval runner sends prompts through Yoker's actual backend pipeline. The
choice of execution path depends on the task type:

**For standard tasks (no tools):**
```python
# Uses yoker.process() — one-shot, no tools, no system prompt
response = await yoker.process(
    prompt=task.prompt,
    model=model,
    config=config,  # temperature=0, seed=42
)
```

**For tool-use tasks:**
```python
# Uses yoker.agent() with specific tools enabled
agent = yoker.agent(model=model, tools=["calculator", "search"])
response = await agent.process(task.prompt)
# Inspect agent's event stream for ToolCallDelta events
```

**For direct backend access (if needed):**
```python
# Uses yoker's ModelBackend directly — full control
async for chunk in backend.chat_stream(
    model=model,
    messages=[{"role": "user", "content": task.prompt}],
):
    if chunk.event == ChatChunkEvent.CONTENT_DELTA:
        response += chunk.text
    elif chunk.event == ChatChunkEvent.USAGE:
        tokens_in = chunk.usage.input_tokens
        tokens_out = chunk.usage.output_tokens
```

### 10.7 UsageStats Mapping

Yoker's `UsageStats` is provider-neutral:

```python
# From backends/protocol.py
class UsageStats:
    input_tokens: int | None = None       # OpenAI/Anthropic
    output_tokens: int | None = None      # OpenAI/Anthropic
    prompt_eval_count: int | None = None  # Ollama native (== input_tokens)
    eval_count: int | None = None         # Ollama native (== output_tokens)
    total_duration_ms: int | None = None  # Ollama native total duration
```

The eval framework normalizes:

```python
tokens_in = usage.input_tokens or usage.prompt_eval_count or 0
tokens_out = usage.output_tokens or usage.eval_count or 0
latency_ms = usage.total_duration_ms or wall_clock_ms
```

## 11. Quantitative Metrics and Cost Model

### 11.1 What Gets Collected Per Task

Two layers of data, collected by different actors:

**Framework-collected (automatic):**

| Metric | Source | Description |
|---|---|---|
| `tokens_in` | `UsageStats.input_tokens` / `prompt_eval_count` | Input tokens consumed |
| `tokens_out` | `UsageStats.output_tokens` / `eval_count` | Output tokens generated |
| `latency_ms` | Wall-clock (prompt → completion) | Total latency |
| `ttft_ms` | Wall-clock (prompt → first token) | Time to first token (if streaming) |

**Scorer-returned:**

| Metric | Source | Description |
|---|---|---|
| `score` | Scorer function | 0.0–1.0 quality score |
| `sub_scores` | Scorer function | Per-component scores (e.g., per test case) |
| `extracted` | Scorer function | What was extracted from the response |

### 11.2 Cost Model — Current (Active)

The current cost factor is **Ollama session/weekly usage % delta**, already
implemented in `usage.py` (`fetch_ollama_usage`) and `report.py`
(`compute_composite` with `cost_delta`).

The composite score formula uses this usage delta:
```
composite = quality × cost_score
where cost_score = 1 / (1 + cost_per_correct × scale)
where cost_per_correct = usage_delta / max(n_correct, 1)
```

Free models (usage_delta = 0 or None) → cost_score = 1.0 → composite = quality.
Models that consume more API usage need higher quality to justify their cost.

### 11.3 Cost Model — Token-Based Pricing (DEFERRED)

> **Deferred per owner decision.** The current primary goal is a quality
> ranking report across all Ollama cloud models using usage % as the cost
> factor. Token-based pricing will be revisited when API models with real
> per-token costs need to be compared.

The framework collects raw tokens and latency. Token-based cost is a derived
metric requiring pricing data, which is external.

**Pricing file (maintained separately from suites):**

```yaml
# pricing.yaml — updated independently (deferred)
models:
  llama3.2:3b:
    provider: ollama
    cost: 0.0                    # local = free
  gpt-4o-mini:
    provider: openai
    input_per_million: 0.15
    output_per_million: 0.60
```

The framework would load pricing once at startup and compute:
`cost = (tokens_in × input_price + tokens_out × output_price) / 1_000_000`.

### 11.4 Cost Per Correct Answer (DEFERRED)

> **Deferred** — depends on token-based pricing (FR10).

A key derived metric for the "cheap vs expensive" differentiation:

```
cost_per_correct_answer = total_cost / (overall_score × n_tasks)
```

A cheap model that gets 70% right for $0.001 has a better
cost-per-correct-answer than an expensive model that gets 95% right for $0.05.

## 12. Public API

### 12.1 Python API

```python
from yoker_test import evaluate, EvalRunner, TestTask, TestReport, Score

# Simple: load suite from YAML, run against a model
report = await evaluate(
    suite="yoker_basic",       # name or path to suite YAML
    model="llama3.2:3b",       # model to test
    compare="baseline.yaml",   # optional baseline to compare against
)

# Or: build a suite programmatically
report = await EvalRunner(
    tasks=[
        TestTask(id="K1", prompt="...", expected="C", scorer="mcq"),
        TestTask(id="R1", prompt="...", expected=36, scorer="numeric_match"),
    ],
    repeats=3,
    temperature=0.0,
).run(model="llama3.2:3b")

# Report is a structured object
print(report.overall.score)          # 0.694
print(report.summary["reasoning"])   # CategorySummary(...)
print(report.comparison.delta)       # {"reasoning": -0.125, ...}

# Serialize
report.to_yaml()                     # → YAML string
report.to_json()                     # → JSON string
```

### 12.2 CLI

```bash
# Run a suite against a model
yoker-test eval --suite yoker_basic --model llama3.2:3b

# Run and compare to a baseline
yoker-test eval --suite yoker_basic --model llama3.2:3b --compare baseline.yaml

# Run a custom suite
yoker-test eval --suite suites/custom/ --model gpt-4o-mini --output report.yaml

# List available suites
yoker-test suites

# Show a suite's tasks without running
yoker-test show --suite yoker_basic
```

## 13. The Minimal Suite: yoker_basic v1.0

A focused set of ~30 tasks across 5 categories, designed to differentiate
models from ~40% (weak 3B) to ~90% (strong API model).

### 13.1 Category Distribution

| Category | Tasks | Scoring | Purpose |
|---|---|---|---|
| Knowledge | 8 | mcq (binary) | Factual knowledge, MCQ format |
| Reasoning | 8 | numeric_match (graded) | Math and logic, numeric answers |
| Instruction Following | 6 | structural (graded) | Format constraint compliance |
| Code Generation | 4 | code_execution (graded) | Write and verify Python code |
| Tool Use | 4 | tool_call_verify (graded) | Emit and parse tool calls |
| **Total** | **30** | | |

### 13.2 Difficulty Distribution

Each category has a mix of easy, medium, and hard tasks:

- **Easy**: all models should get these right (~90%+). If missed, either the
  model is very weak or Yoker's prompt formatting broke.
- **Medium**: mid-tier models start missing some. This is where
  differentiation begins.
- **Hard**: only strong models succeed. This separates the top tier.

### 13.3 Graded Scoring

Binary scoring (0/1) with 30 prompts gives ~3.3% resolution per prompt.
Graded scoring (0, 0.25, 0.5, 0.75, 1.0) gives ~120+ distinct combinations.
This detects finer shifts — a model that was getting 0.75 on a code task
(3/4 test cases) and now gets 0.50 (2/4) is a detectable change even though
binary scoring would show no difference.

### 13.4 Expected Score Spread

| Model | Knowledge (8) | Reasoning (8) | Instr. (6) | Code (4) | Tools (4) | Total | % |
|---|---|---|---|---|---|---|---|
| 3B model | 5 | 3 | 2 | 1 | 1 | 12 | 40% |
| 7B model | 6 | 4 | 3 | 2 | 2 | 17 | 57% |
| 70B model | 7 | 6 | 4 | 3 | 3 | 23 | 77% |
| GPT-4o | 8 | 7 | 5 | 3.5 | 3.5 | 27 | 90% |

This 40%–90% spread is what makes the suite meaningful — not too easy, not too
hard.

### 13.5 Aggregation Weights

```yaml
aggregation:
  weights:
    knowledge: 0.25
    reasoning: 0.25
    instruction: 0.20
    code: 0.15
    tool_use: 0.15
```

## 14. The Framework's Execution Loop

```
Load suite config
  → parse YAML
  → resolve !function references to Python callables
  → if task_generator: call it → get tasks
  → else: use static tasks from YAML
  → for each task: resolve scorer (built-in name → function, or use callable)

For each task × repeat:
  → record start time
  → if task has turns: send each turn through Yoker, collect responses, build messages list
  → else: send task.prompt through Yoker (process() or backend.chat_stream())
  → collect: response text, UsageStats (tokens_in, tokens_out, total_duration_ms)
  → record end time → compute latency_ms, ttft_ms
  → call scorer(task, response) → score (float or Score object)
  → unpack Score → score, extracted, sub_scores
  → assemble TestResult
  → handle errors (timeout, API error → error string, score = 0.0)

Aggregate:
  → group results by category
  → per category: mean score, std, avg tokens, avg latency
  → overall: weighted mean (weights from config or uniform)
  → total tokens, total latency, avg tokens/sec
  → fetch Ollama usage before/after → usage_delta (session/weekly % delta)
  → composite = quality × cost_score (cost_score from usage_delta, NOT token pricing)

Compare (if baseline provided):
  → load baseline report
  → compute delta per category and overall
  → flag if |delta| > threshold (e.g., 2 × std)

Output report (YAML/JSON + optional human summary + quality ranking table)
```

## 15. Comparison With Existing Frameworks

### 15.1 What Makes yoker-test Unique

1. **Runs through Yoker** — tests the actual pipeline, not just the model.
   No other framework tests their own infrastructure.
2. **Regression testing** — baseline comparison to detect Yoker changes.
   No other framework does this because they don't have a "host framework"
   to regress against.
3. **Efficiency metrics** — tokens, latency, tokens/sec, cost as first-class
   metrics. No other framework reports these alongside quality.
4. **Configuration-driven** — test suites are YAML + optional Python, framework
   is a small generic engine.

### 15.2 What We Adopt

**From lm-evaluation-harness:** YAML task definitions with versioning, regex
filter chains, bootstrap CIs, dual-filter approach for numeric extraction.

**From simple-evals:** `normalize_response` function, zero-shot CoT prompt
template, bootstrap std computation, LLM equality checker concept.

**From Inspect AI:** Clean `Sample(input, target)` + `scorer` separation,
clustered standard errors, epochs for repeated runs, sandboxed code execution.

**From reliability research:** Temperature=0 is necessary but not sufficient,
3 runs is usually enough, local models are the only truly deterministic ones,
report mean ± std, document everything.

### 15.3 What We Don't Claim

- Our scores will **not match** lm-eval's MMLU scores or simple-evals' GPQA
  scores. Different prompts, different extraction, different scoring.
- We are **not** building 1000+ tasks. A focused suite of ~30-65 tasks.
- We are **not** building a leaderboard. The landscape overview is for Yoker
  users, not for the broader ML community.

## 16. Yoker Package Split Context

yoker-test serves as the **testbed for the Yoker package split**. The patterns
established here (CommandSpec, PluginManifest extension, dynamic command
discovery, config injection) will be the blueprint for extracting other
subcommands from the yoker monolith.

### 16.1 The Split Vision

Split the monolithic `yoker` package into several focused, independently
versioned packages. Each provides a distinct capability while sharing a common
SDK foundation.

**Goals:**
- **Lean core**: `yoker` becomes a pure SDK — Agent, Session, backends, config,
  context, events, tools, plugins, built-in tools. No CLI subcommands, no
  interactive UI, no bootstrap wizard.
- **Fine-grained installation**: `uv add yoker[chat]` or `uv add yoker-chat`
  installs only what you need.
- **Independent versioning**: each package releases on its own cadence.
- **Reduced test scope**: each package has its own test suite.
- **Extensibility**: third-party packages provide new `yoker` subcommands via
  an extended plugin manifest.

**Non-goals:** Backward compatibility (pre-1.0.0, breaking change), no uv
workspace (packages in separate repos), no separate `yoker-ui` package
(yoker-chat is the UI package).

### 16.2 Package Overview

| # | Package | Purpose | Depends on | Key external deps |
|---|---|---|---|---|
| 1 | **yoker** | Core SDK: Agent, Session, backends, config, context, events, tools, plugins, built-in tools | — | litellm, ollama, httpx, structlog, clevis, dacite, pyyaml |
| 2 | **yoker-chat** | Interactive REPL, UI handlers, slash commands, demo/session SVG export | yoker | prompt_toolkit, rich, pyfiglet |
| 3 | **yoker-run** | Batch execution (`run` + `loop`), source resolution | yoker | — |
| 4 | **yoker-inspect** | Source inspection/reporting | yoker | — |
| 5 | **yoker-config** | First-run bootstrap wizard, `init`, `config` display | yoker | rich, pyfiglet |
| 6 | **yoker-container** | Container/Dockerfile generation | yoker | — |
| 7 | **yoker-test** | Model evaluation framework (new) | yoker | — |

### 16.3 Dependency Graph

```
                    yoker (core SDK)
                   /  |    |    |    \     \      \
          yoker-chat yoker-run yoker-inspect yoker-config yoker-container yoker-test
```

Each subcommand package:
- Depends on `yoker` (core)
- Has its own `pyproject.toml`, tests, CI, Makefile
- Declares a `__YOKER_MANIFEST__` with a `commands` entry
- Can be installed independently (`uv add yoker-chat`) or via extras
  (`uv add yoker[chat]`)

### 16.4 Extras Mechanism

The core `yoker` package declares optional-dependency extras:

```toml
[project.optional-dependencies]
chat = ["yoker-chat"]
run = ["yoker-run"]
inspect = ["yoker-inspect"]
config = ["yoker-config"]
container = ["yoker-container"]
test = ["yoker-test"]
all = ["yoker-chat", "yoker-run", "yoker-inspect", "yoker-config",
       "yoker-container", "yoker-test"]
```

Both `uv add yoker[chat]` and `uv add yoker-chat` converge: the former pulls
yoker-chat via the extra, the latter pulls yoker via yoker-chat's dependency
declaration.

### 16.5 CommandSpec

```python
@dataclass
class CommandSpec:
  name: str                          # subcommand name (e.g., "test")
  handler: Callable[..., Any]        # entry point function
  config_class: type | None = None   # optional Clevis config class
  help: str = ""                     # help text
  default: bool = False              # is this the default subcommand?
```

### 16.6 PluginManifest Extension

```python
@dataclass
class PluginManifest:
  # ... existing fields ...
  commands: list[CommandSpec] = field(default_factory=list)
  config_sections: dict[str, type] = field(default_factory=dict)
```

- `commands`: declares subcommands the package provides
- `config_sections`: declares configuration classes to inject into the config
  hierarchy (e.g., `{"test": TestConfig}` → available at `config.test`)

### 16.7 Configuration Injection

A plugin provides its config classes along with an injection path — a location
in the existing config hierarchy where the class should be attached:

```python
# yoker_test/__init__.py
__YOKER_MANIFEST__ = PluginManifest(
  commands=[CommandSpec(name="test", handler=run_test, config_class=TestConfig)],
  config_sections={
    "test": TestConfig,  # injected at config.test
  },
)
```

The injection path is the key name in the `config_sections` dict. The core
config loader discovers `config_sections` from installed packages' manifests
and attaches the config classes to the `Config` hierarchy at the specified
paths.

For subcommand-specific config (CLI args, TOML sections), each package's
config class extends `yoker.Config`:

```python
# yoker_test/config.py
from yoker.config import Config

class TestConfig(Config):
  suite: str = "yoker_basic"
  model: str = "glm-5.2:cloud"
  compare: str | None = None
  output: str | None = None
  repeats: int = 3
```

Clevis treats this as a subcommand config — extracts the `[test]` section from
TOML, generates CLI args from the dataclass fields.

### 16.8 ConfigIsMissing

Core yoker raises `ConfigIsMissing` when no config file is found. If
yoker-config is installed, it catches this exception and runs the bootstrap
wizard gracefully. If yoker-config is not installed (e.g., batch-only
installations), the error surfaces with guidance.

```python
# yoker core
class ConfigIsMissing(YokerError):
  """No yoker configuration file found."""
  def __init__(self) -> None:
    super().__init__(
      "enabled", "true",
      "No yoker configuration found. Run `yoker init` to create one, "
      "or see https://yoker.dev for documentation."
    )
```

### 16.9 The yoker Router

With only the core SDK installed, the `yoker` command:
1. Discovers installed yoker-* packages (via plugin loader)
2. Collects `CommandSpec`s from their `__YOKER_MANIFEST__`
3. Builds the CLI dynamically
4. Dispatches to the matching handler

When no subcommand packages are installed, `yoker` prints available subcommands
(none) and suggests packages to install:

```
$ yoker
No yoker subcommands are installed.

Available packages:
  yoker-chat      Interactive REPL
  yoker-run       Batch execution
  yoker-inspect   Source inspection
  yoker-config    Configuration management
  yoker-container Container generation
  yoker-test      Model evaluation

Install with: pip install yoker-chat  (or: pip install yoker[chat])
```

The subcommand name is `test` — `yoker test`, not `yoker eval`.

### 16.10 Clevis Extensions Needed

1. **Dynamic command registration**: register a config class as a subcommand
   at runtime (not just via `@configclass` decorator at import time)
2. **Build CLI from a list of specs**: construct an argparse parser from a
   list of dynamically discovered subcommands (name, config_class, help text,
   default flag)
3. **`get_cmd()` with dynamic subcommands**: the dispatch function works with
   subcommands registered at runtime, not just at import time
4. **Subcommands without a base Config class**: lightweight commands like
   `inspect` that don't extend `Config` should still be registerable
5. **Default subcommand designation**: one subcommand can be marked as default
   (runs when no subcommand is given). Currently `chat` is the default
6. **Dynamic config section injection**: attaching plugin-provided config
   classes at specified paths in the config hierarchy

**Strategy**: Discover through yoker-test implementation. Create specific
feature requests to Clevis as needs are discovered. Start with a simple router
(may not need Clevis for top-level dispatch), discover if Clevis is needed.
The router might just discover `CommandSpec`s and dispatch via its own
argparse-based mechanism — Clevis would still be used *inside* each subcommand
for config loading via `get_config()`.

### 16.11 Split Phasing Strategy

**Drive the split from `yoker-test`.** yoker-test is the first new package
built with the new patterns. It serves as the testbed and blueprint. After
yoker-test is proven, existing subcommands are extracted one by one.

```
Phase 0  Clevis extension (discovered through yoker-test)
Phase 1  yoker-test (testbed for new patterns)
Phase 2  Extract yoker-chat
Phase 3  Extract yoker-run
Phase 4  Extract yoker-config
Phase 5  Extract yoker-inspect
Phase 6  Extract yoker-container
```

### 16.12 Confirmed Decisions (from split analysis)

| # | Decision |
|---|---|
| D1 | Bootstrap → yoker-config. Core raises `ConfigIsMissing` when no config found. |
| D2 | `PluginManifest` extended with `commands: list[CommandSpec]` and `config_sections: dict[str, type]`. |
| D3 | Clevis extended to support dynamic registration. Feature requests created as needs are discovered through yoker-test. |
| D4 | Separate repos, no uv workspace. |
| D5 | Config injection: plugin provides config class + injection path into config hierarchy. |
| D6 | Built-in tools stay in yoker core. |
| D7 | Demo/Session SVG → yoker-chat, integrated as a chat option. |
| D8 | No separate yoker-ui. yoker-chat is the UI package. |
| D9 | `yoker` command is a router. Shows help when no subcommands installed. |
| D10 | Extras: `yoker[chat]`, `yoker[run]`, ..., `yoker[all]`. |
| D11 | `markdown.py` → yoker-chat (only meaningful in UI context). |
| D12 | Examples split across packages. |
| D13 | Shared utils split by usage (generic → core, run-specific → yoker-run). |
| D14 | Each package has own Makefile. |
| D15 | Demo `yoker.toml` → yoker-chat. |
| D16 | One documentation site in yoker core repo. Future: yoker.dev site. |
| D17 | Independent versioning per package. |
| D18 | Breaking change, no migration path (pre-1.0.0). |
| D19 | Demo plugin: dropped or split — deferred. |
| D20 | Config writer (`config/writer.py`) → yoker-config. |
| D21 | Each package has own test setup (possibly with duplicated fixtures). |
| D22 | CI: packages depend on a version of yoker, live independently. |
| D23 | Phasing: drive from yoker-test first. yoker-test is the testbed and blueprint. |
| D24 | `UIHandler` protocol, `UIBridge`, `BatchUIHandler`, `formatting.py` stay in yoker core (no heavy deps). |
| D25 | `InteractiveUIHandler`, `markdown.py`, slash commands → yoker-chat. |
| D26 | Per-package UI config (`ChatUIConfig`, `RunUIConfig`). `UIConfig` removed from core `Config`. |
| D27 | `SessionConfig` stays in core `Config`. `ChatConfig`'s session_id/resume → yoker-chat. |
| D28 | Core exports what packages need (`UIHandler`, `UIBridge`, `BatchUIHandler`, `CommandSpec`, etc.). |
| D29 | Subcommand name is `test` — `yoker test`, not `yoker eval`. |
| D30 | yoker-config provides `WizardUIHandler` (stdlib) — no dependency on yoker-chat. |

### 16.13 Open Questions (from split analysis)

| # | Question | Status |
|---|---|---|
| OQ-1 | What exactly should the Clevis API look like for runtime command registration? | Discover through yoker-test implementation |
| OQ-2 | How does config injection work concretely? Does Clevis support this? | Discover through yoker-test implementation |
| OQ-3 | Does the `yoker` core `__main__.py` router need Clevis at all? | Start with simple router, discover if Clevis needed |
| OQ-4 | Does yoker-test need UI at all? Use `BatchUIHandler` or own output mechanism? | Start with own output (option b), switch if consistency needed |
| OQ-5 | Drop or split the demo plugin (`examples/plugins/demo`)? | Deferred |
| OQ-6 | How does the single docs site work when packages are in separate repos? | Docs in yoker core repo for now |
| OQ-7 | Where does `BatchUIHandler` get display settings after `UIConfig` removed? | Resolved: each package passes own UI config values as constructor args |
| OQ-8 | How does yoker-config's wizard get interactive input without yoker-chat? | Resolved: `WizardUIHandler` using stdlib (`input()`, `getpass()`) |

## 17. Non-Functional Requirements

### NFR1: Coding Standards
- 2-space indentation (matches yoker)
- Double quotes
- Line length: 100
- Ruff for formatting and linting
- Mypy for type checking (strict mode)
- Conventional commits with attribution: `🤖 Implemented together with Yoker.`

### NFR2: Testing Approach
- Unit tests for every module (pytest + pytest-asyncio)
- Mocked external dependencies (Yoker SDK, httpx, file I/O)
- Test behavior, not implementation
- Tests grow as functionality stabilizes (Phase 1: minimal, Phase 2: full)
- Scorers unit-tested against known model output samples

### NFR3: Python Compatibility
- Python >= 3.10
- Uses `str | None` union syntax (3.10+)
- `dataclasses` for all data structures

### NFR4: Package Management
- uv as package manager
- Editable yoker dependency from `../yoker`
- Hatchling as build backend
- Standalone package, not a yoker submodule

### NFR5: Error Handling
- Per-task errors don't abort the suite (record error, score 0.0, continue)
- External API failures degrade gracefully (return None, continue)
- Missing config sections return None, not exceptions
- `!function` resolution failures fail at load time with clear error

### NFR6: Configurability
- Suite-driven (not hardcoded tasks)
- Scorer selection per-task via suite YAML
- Category weights configurable (`aggregation.weights` in suite YAML)
- Runtime config: temperature, seed, repeats (from suite YAML)
- Composite scale configurable
- Regression threshold: `|delta| > 2 × std` (statistical, not fixed)

### NFR7: Determinism Settings
- Temperature=0 (default, from suite config)
- Fixed seed (default: 42, from suite config)
- Run N=3 repeats (default, from suite config)
- Prefer Ollama (local) models for baselines

### NFR8: Suite Versioning
- Suite version in YAML (`version: "1.0"`)
- Baselines only comparable within same suite version
- Never change prompts without bumping suite version

## 18. Current State vs Target State

### Phase 1: Extract Monolith — ✅ Complete

All code extracted from `__main__.py` into 6 submodules with unit tests:
- `schema.py` — `TestTask`, `TestResult` dataclasses
- `scorers.py` — `mcq_scorer` + `SCORERS` registry (4-stage fallback)
- `usage.py` — `fetch_ollama_usage` (Ollama API usage fetching)
- `runner.py` — `StatsCollector` + `run_single_test`
- `report.py` — `compute_composite` + `print_report`
- `cli.py` — `main`/`async_main` (argparse, orchestration)
- `__main__.py` — thin entry point

Tests cover all modules with mocked dependencies.

### Phase 2: Extend to Full Form — Not Started

The system currently:
- ✅ Runs a single hardcoded MCQ task
- ✅ Scores with MCQ scorer only
- ✅ Collects tokens, latency, thinking/content split
- ✅ Fetches Ollama usage deltas
- ✅ Computes composite score
- ✅ Prints single-task console report

The system needs to:
- ❌ Define and load test suites from YAML (with `!function` resolution)
- ❌ Support 7 built-in scorer types + custom scorers
- ❌ Execute full suites with multiple tasks × repeats
- ❌ Support multi-turn conversations (sequential turns, full message exchange)
- ❌ Aggregate results by category (mean ± std, efficiency metrics)
- ❌ Compare against stored baselines (regression detection)
- ❌ ~~Compute costs from pricing data~~ (DEFERRED — use Ollama usage % instead)
- ❌ Provide `eval`, `suites`, `show` subcommands
- ❌ Output YAML/JSON reports (with `to_yaml()`, `to_json()`, `to_dict()`)
- ❌ Support `task_generator` for dynamic suites
- ❌ Provide Python public API (`evaluate()`, `EvalRunner`)
- ❌ Create `config.py` with `TestConfig(yoker.Config)`
- ❌ Create `yoker_basic` suite (30 tasks, 5 categories)
- ❌ Generate quality ranking report across all Ollama cloud models (primary deliverable)
- ❌ Generate landscape overview (model compatibility table)
- ❌ Maintain baseline registry (`baselines/registry.yaml`)
- ❌ Support three execution paths (`process()`, `agent()`, `backend.chat_stream()`)
- ❌ Handle model refusals (record as error, score 0.0, flag "refused")
- ❌ Provide bootstrap confidence intervals
- ❌ Support dual-filter numeric extraction (strict + flexible)
- ❌ Collect TTFT (time to first token) for streaming
- ❌ Define reference model set for regression baselines

### Phase 3: Yoker Modifications — Not Started

Patterns to establish for the Yoker package split:
- ❌ `CommandSpec` dataclass in `yoker.plugins.manifest` (with `handler:
  Callable`, `config_class`, `help`, `default`)
- ❌ `commands: list[CommandSpec]` and `config_sections: dict[str, type]`
  fields in `PluginManifest`
- ❌ Dynamic command discovery from installed packages in `yoker.__main__`
- ❌ `yoker test` subcommand wired via discovery (subcommand name is `test`)
- ❌ `ConfigIsMissing` exception in yoker core (confirmed, not conditional)
- ❌ Clevis extensions for dynamic command registration and config injection

## 19. Phasing (from design doc)

| Phase | Scope | Output |
|---|---|---|
| **Phase 1** | Core runner + 6 built-in scorers + yoker_basic suite (30 tasks) + basic report + baseline comparison | Can score any Ollama/API model on quality + efficiency, detect Yoker regressions |
| **Phase 2** | Tool-use evaluation + multi-turn context tests + statistical significance + variance reporting | Full agentic capability profile |
| **Phase 3** | Cross-backend comparison (same model, different Yoker backend) + auto-generated compatibility docs | Adapter bug detection, living documentation |
| **Phase 4** | LLM-as-judge scorer (optional) + custom task generators + suite marketplace | Domain-specific evals, community suites |

Note: The project's TODO.md currently tracks Phase 2 (extend submodules) and
Phase 3 (yoker modifications) as the immediate next work. The design doc's
Phase 2-4 are future capabilities beyond the current TODO scope.

## 20. Open Questions

### From yoker-test-analysis.md

1. **Separate repo or same repo?** Recommendation: separate repo, separate
   package. Different audiences and release cycles.
2. **Models that refuse to answer?** Record as error, score 0.0, flag in
   report as "refused" if detected.
3. **Streaming vs non-streaming?** Collect all chunks for full response.
   Measure TTFT and total generation time separately.
4. **Pricing updates?** Pricing file is external and versioned separately.
   Old reports keep computed cost; re-running with updated pricing may change
   cost numbers (but not quality numbers).
5. **Support existing lm-eval-harness tasks?** Not in Phase 1. The `!function`
   mechanism allows users to write their own adapters.
6. **Multi-turn evaluation?** Now in scope (FR18). The suite format and runner
   support multi-turn conversations (sequential turns with full message
   exchange). Needed to create complex enough tests to differentiate models.
7. **Thinking mode?** Default off, optional per-task override in suite config.

### From yoker-split-analysis.md

8. **OQ-1: Clevis API for dynamic command registration** — What exactly
   should the Clevis API look like for runtime command registration?
   Strategy: Discover through yoker-test implementation.
9. **OQ-2: Config injection mechanism** — How does config injection work
   concretely? Does Clevis support this? How does TOML section extraction
   work for injected configs? Strategy: Discover through yoker-test
   implementation.
10. **OQ-3: Does the router need Clevis?** — Can the top-level router be a
    simple argparse-based dispatcher that doesn't use Clevis's `get_cmd()`?
    Clevis would still be used *inside* each subcommand. Strategy: Start with
    a simple router, see if Clevis is needed.
11. **OQ-4: yoker-test UI dependency** — Does yoker-test need UI at all?
    Options: (a) `BatchUIHandler` from core, (b) own output mechanism.
    Strategy: Start with (b), switch to (a) if consistency is needed.
12. **OQ-5: Demo plugin** — Drop or split the demo plugin? Deferred.
13. **OQ-6: Documentation site structure** — How does the single docs site
    work when packages are in separate repos? Docs in yoker core repo for now.

## 21. Dependencies

### Runtime Dependencies
- `yoker>=0.10.1` — Agent SDK, config, event system, backends
- `httpx>=0.25.0` — Async HTTP for Ollama usage API

### Development Dependencies
- `pytest>=8.0.0` — Test framework
- `pytest-asyncio>=0.23.0` — Async test support
- `pytest-mock>=3.10.0` — Mocking utilities
- `mypy>=1.13.0` — Type checking
- `ruff>=0.8.0` — Formatting and linting

### Planned Dependencies (Phase 2)
- `pyyaml` — Suite YAML loading

## 22. Target Models

The framework is designed to test against Ollama cloud-available models
(see `docs/models.md`):

- deepseek-v4-flash, deepseek-v4-pro
- gemma4
- glm-5.1, glm-5.2
- gpt-oss (20b, 120b)
- kimi-k2.6, kimi-k2.7-code, kimi-k3
- minimax-m2.7, minimax-m3
- nemotron-3 (nano, super, ultra)
- qwen3.5

The default model is `glm-5.2:cloud`.

For regression baselines, prefer local Ollama models (deterministic). API
models can silently update, making baselines unreliable over time.