## Security Review Report: P2.4 — EvalRunner in runner.py

### Executive Summary

yoker-test is a developer-run evaluation tool, not a production service. The threat model is fundamentally different: the primary user is a trusted developer running suites they wrote or reviewed against API endpoints they configured. The attack surface is narrow but not zero — suite files can be shared, yoker SDK executes model-generated tool calls, and the `code_execution` scorer runs model-generated code. The most significant finding is the `code_execution` scorer's sandbox being bypassable (Medium), followed by error message leakage patterns (Low) and resource exhaustion risks (Low). No Critical or High findings.

---

### Scope

This review covers the planned `EvalRunner` class (P2.4) and its interaction with:
- `runner.py` — current `StatsCollector` and `run_single_test`
- `scorers.py` — all scorers, especially `code_execution`
- `loader.py` — YAML suite loading and `!function` tag resolution
- `schema.py` — `TestReport` serialization (`to_yaml`, `to_json`)
- `usage.py` — Ollama API usage fetching
- Three execution paths: `yoker.process()`, `yoker.agent()`, `backend.chat_stream()`

---

### Critical Findings (CVSS 9.0-10.0)

None.

---

### High Findings (CVSS 7.0-8.9)

None.

---

### Medium Findings (CVSS 4.0-6.9)

#### M1: code_execution scorer sandbox is bypassable (OWASP A05 — Injection)

**Confidence**: High

The `code_execution` scorer in `scorers.py` uses `exec()` with a restricted `__builtins__` dict:

```python
def run_code(c: str = code, ns: dict = local_ns) -> None:
    exec(c, {"__builtins__": _RESTRICTED_BUILTINS}, ns)
```

The `_RESTRICTED_BUILTINS` approach is a well-known weak sandbox. Model-generated code can escape it via:

1. **Class introspection**: `().__class__.__bases__[0].__subclasses__()` to find `os`, `subprocess`, etc.
2. **`__import__` via builtins**: `type.__subclasses__(type)` chains can reach `__builtins__['__import__']`.
3. **Attribute traversal**: Any object in the restricted builtins (e.g., `list`, `dict`) provides a path to `object.__subclasses__()`.

This runs in the main process with full privileges.

**Impact**: If a model produces malicious code (e.g., via prompt injection in a shared suite file), the scorer executes it with the developer's full filesystem, network, and process access. This is the most significant finding because:
- Suite files can be shared between developers/organizations
- The code comes from model output, not from the suite file directly — but a malicious suite prompt could instruct the model to generate exploitative code
- The `ThreadPoolExecutor` timeout does not prevent side effects (file writes, network calls, subprocess spawning) — it only limits execution time

**Remediation**: This is an inherent design tradeoff of a code execution scorer. Options (in order of preference):

1. **Document the risk explicitly** in suite format docs and in a warning printed at suite load time when `code_execution` tasks are present. This is the minimum bar.
2. **Add a `--allow-code-execution` CLI flag** that must be explicitly set. Without it, `code_execution` tasks are skipped with a warning.
3. **Run in a subprocess with `resource.setrlimit`** (CPU/memory limits) and no network access — more robust than `__builtins__` restriction but still not a true sandbox.
4. **True sandbox** (container, wasmtime, etc.) — out of scope for this project's complexity level.

**Owner's proposal assessment**: The current `_RESTRICTED_BUILTINS` approach is the owner's existing implementation. It provides a basic guard but is known-bypassable. For an evaluation tool run by trusted developers, option 1 (document the risk) plus option 2 (explicit CLI opt-in) is proportionate. The added complexity of options 3-4 is not justified at this stage.

**Reference**: [CWE-95: Improper Neutralization of Directives in Dynamically Evaluated Code](https://cwe.mitre.org/data/definitions/95.html)

---

#### M2: `!function` YAML tag enables arbitrary code import (OWASP A05 — Injection)

**Confidence**: High

The `loader.py` resolves `!function` YAML tags via `importlib.import_module` + `getattr`:

```python
def _resolve_function(dotted_path: str) -> Callable:
    module_path, attr_name = parts
    module = importlib.import_module(module_path)
    func = getattr(module, attr_name)
    return func
```

This executes at YAML load time, before any suite validation. A malicious YAML file can import any installed Python module and access any attribute:

```yaml
task_generator: !function os.system
generator_config: {command: "rm -rf /"}
```

Wait — `os.system` is a function and would be called with `generator_config` as its argument during suite execution. But even without `task_generator`, a `!function` tag in a `scorer` field would import arbitrary code.

**Impact**: A shared/external suite file can execute arbitrary code at load time via import side effects, or at execution time via the resolved callable.

**Remediation**:
- The current design is intentional for extensibility (custom scorers, task generators). The trust boundary is "suite files are trusted, like source code."
- Add a warning when loading suites with `!function` tags: `Warning: suite uses !function imports — verify the suite source is trusted.`
- Do NOT add an allowlist — it would break the extensibility use case.
- Document in suite format docs that `!function` is equivalent to running Python code from the suite file.

**Owner's proposal assessment**: The `!function` mechanism is the owner's explicit design. It works as intended. The risk is real but proportionate to the tool's trust model. A warning at load time is the right level of response.

**Reference**: [CWE-94: Improper Control of Generation of Code](https://cwe.mitre.org/data/definitions/94.html)

---

### Low Findings (CVSS 0.1-3.9)

#### L1: Error messages may leak sensitive information (OWASP A10 — Exception Handling Failures)

**Confidence**: Medium

The current `run_single_test` catches all exceptions and records `str(exc)`:

```python
try:
    response = await agent.process(task.prompt)
except Exception as exc:
    response = ""
    error = str(exc)
```

The `EvalRunner` will follow the same pattern (per P2.4: "record error, score 0.0, continue suite"). Exception messages from the Yoker SDK or backend client may include:
- API keys in URL strings (e.g., `httpx.ConnectError: [ConnectError] https://api.example.com/v1/chat?key=sk-...`)
- Internal filesystem paths (e.g., config file paths in `FileNotFoundError`)
- Backend provider details

These error strings end up in `TestResult.error`, which is serialized via `TestReport.to_yaml()` and `TestReport.to_json()`.

**Impact**: If a report is shared (e.g., for regression comparison, published results), the error field could contain API keys or internal paths. The risk is low because:
- The tool is developer-run, not public-facing
- API keys are typically in headers, not URLs, for most providers
- Filesystem paths are not highly sensitive in a dev tool

**Remediation**:
- Sanitize error messages before storing in `TestResult.error`: strip patterns matching common API key formats (`sk-...`, `Bearer ...`, `sk-or-...`)
- Truncate error messages to a reasonable length (e.g., 500 chars)
- Consider storing error type separately from error message: `error_type: str` (e.g., "ConnectionError") + `error_message: str` (sanitized)

**Practical recommendation**: Add a `sanitize_error(msg: str) -> str` utility that redacts known secret patterns and truncates. Call it before storing in `TestResult.error`. This is proportionate and low-cost.

---

#### L2: No timeout on individual task execution (OWASP A06 — Insecure Design)

**Confidence**: High

The current `run_single_test` has no overall timeout. The `EvalRunner` will execute `tasks × repeats` tasks sequentially. A single task that hangs (e.g., model in a loop, backend unresponsive) blocks the entire suite.

The `StatsCollector` relies on Yoker SDK's internal timeout, and `fetch_ollama_usage` has a 10-second httpx timeout, but the main execution path has none.

**Impact**: A hung task wastes API quota (if the backend keeps generating) and blocks suite completion. With `repeats=3` and many tasks, a single hang can block for a very long time.

**Remediation**:
- Add `asyncio.wait_for(agent.process(task.prompt), timeout=task_timeout)` in the EvalRunner, where `task_timeout` is configurable (default: 60s or from suite config)
- Catch `asyncio.TimeoutError` and record as error with `"timeout"` flag
- Add `SuiteConfig.task_timeout: float | None = None` field

**Practical recommendation**: Simple `asyncio.wait_for` wrapper. ~3 lines of code. Proportionate.

---

#### L3: No rate limiting between API calls (OWASP A06 — Insecure Design)

**Confidence**: Medium

The `EvalRunner` will execute tasks × repeats against external APIs. With `repeats=3` and, say, 50 tasks, that's 150 API calls in rapid succession. Most API providers have rate limits that will return 429 errors, which are caught as generic exceptions and recorded as errors — wasting a repeat slot.

**Impact**: Rate-limit errors inflate error counts, skew results, and waste time. Not a security vulnerability per se, but an operational reliability concern that affects the tool's usefulness.

**Remediation**:
- Add configurable delay between tasks: `SuiteConfig.inter_task_delay: float = 0.0`
- Implement exponential backoff on 429 responses (retry with increasing delay)
- Log rate-limit hits separately from other errors

**Practical recommendation**: Start with a configurable inter-task delay. Backoff on 429 is a nice-to-have but can be deferred. This is operational, not security-critical.

---

#### L4: TestReport serialization may expose config details (OWASP A02 — Security Misconfiguration)

**Confidence**: Low

`TestReport.to_dict()` uses `dataclasses.asdict()`, which recursively converts all fields. `RunMetadata` contains: suite, version, model, provider, yoker_version, temperature, seed, repeats, timestamp. This is all metadata — no secrets.

`TestResult` contains: response, error, tokens, latency, etc. The `response` field contains model output (potentially including prompts echoed back). The `error` field is covered by L1.

The `messages` field in `TestResult` (for multi-turn conversations) will contain the full conversation including the system prompt, which may contain sensitive instructions.

**Impact**: Low. The metadata is not sensitive. The main risk is the `error` field (L1) and `messages` field containing conversation transcripts that could reveal system prompts.

**Remediation**:
- No action needed on `RunMetadata` — it's all metadata
- For `TestResult.messages`: consider a `include_messages: bool = False` flag in `SuiteConfig` to control whether full message transcripts are included in the report
- For `TestResult.error`: see L1

---

### Specific Topic Analysis

#### 1. Code Execution Safety: yoker.process() and yoker.agent() Tool Calls

The `EvalRunner` will use three execution paths:
- `yoker.process()` — one-shot, no tools (safe, no code execution beyond the model's response text)
- `yoker.agent()` — tool-use tasks, the agent can call tools (calculator, search, etc.)
- `backend.chat_stream()` — direct backend access

**Security implication of `yoker.agent()`**: When tools are enabled, the model can invoke tool functions. The tools are defined by the Yoker SDK or by the suite config. The runner does not control which tools the agent has access to — it passes `tools` from the task config.

**Risk**: If a suite enables dangerous tools (e.g., shell access, file read/write), the model's responses could trigger those tools during evaluation. The model is acting on prompts from the suite file.

**Assessment**: This is a Yoker SDK concern, not a yoker-test concern. The runner's job is to pass the tool list through. The trust boundary is at the suite file level — the developer choosing which tools to enable. This is acceptable for the tool's trust model.

**Classification**: Related — document that tool-enabled tasks execute real tool calls with real side effects.

#### 2. Input Handling: YAML Suite File Validation

The `loader.py` already has `validate_suite()` which checks:
- Required fields (id, category, prompt, scorer)
- Duplicate task IDs
- Known scorer names
- Task generator output types

**Gaps identified**:
- **No prompt size limit**: A suite could contain extremely large prompts, causing API rejection or token waste. Not a security issue — operational.
- **No expected value validation**: `expected` is `Any` type. Scorers handle type coercion at evaluation time. Not a security issue.
- **scorer_config is a raw dict**: Passed directly to scorers. The `code_execution` scorer's `test_cases` contain `args` and `expected` values that are passed to `func(*args)` — no validation that args are safe types. However, these come from the suite file (trusted), not from model output.
- **`!function` resolution at load time**: Covered in M2.

**Assessment**: The validation is adequate for the trust model. The suite file is trusted source code, not untrusted user input. No additional validation needed for security purposes.

#### 3. Error Handling Security

Covered in L1. The key concern is `str(exc)` leaking into reports. The `EvalRunner` should sanitize error messages. The current pattern of catching `Exception` broadly is correct for graceful degradation — no change needed to the catch logic, only to the stored message.

#### 4. Model Refusal Detection

The P2.4 spec says: "Detect model refusals (empty response, safety filter) — record as error with 'refused' flag."

**Security concern — false negatives**: A model could produce a partial response that looks like a valid answer but is actually a refusal paraphrase. The refusal detector would need heuristics. If these heuristics use regex patterns, they could be bypassed by creative phrasing. This is a scoring accuracy issue, not a security vulnerability.

**Security concern — false positives**: An aggressive refusal detector could flag legitimate responses as refusals, zeroing their score. This could be exploited if a suite is designed to make certain models look bad. However, the suite author is trusted.

**Assessment**: No security issue. Refusal detection is a scoring accuracy concern, not a security concern. The patterns should be conservative (empty response, explicit "I cannot/I will not" prefixes) to minimize false positives.

#### 5. Resource Exhaustion

Covered in L2 (no timeout) and L3 (no rate limiting). Additional considerations:

- **Connection pool management**: `fetch_ollama_usage` creates a new `httpx.AsyncClient` per call. The `EvalRunner` calls it before and after the full suite, so this is fine. The main execution path uses Yoker's backend, which manages its own connection pool. No issue.
- **Memory**: With `repeats=3` and many tasks, `TestResult` objects accumulate. Each contains a `response` string (model output) and potentially `messages` (full conversation). For large suites, this could use significant memory. Not a security issue — operational.
- **Disk**: `TestReport.to_yaml()` / `to_json()` serialization writes to disk. No issue unless the report is extremely large (thousands of tasks × repeats).

#### 6. Data Exposure in TestReport Serialization

Covered in L1 (error messages) and L4 (message transcripts).

**Specific check on RunMetadata fields**: `suite`, `version`, `model`, `provider`, `yoker_version`, `temperature`, `seed`, `repeats`, `timestamp`. None of these contain secrets. The `provider` field reveals which backend is used, which is acceptable for a test report.

**Specific check on TestResult fields**: `response`, `error`, `extracted`, `tokens_in`, `tokens_out`, `latency_ms`, `thinking_chars`, `content_chars`, `prompt`, `messages`, `sub_scores`. The `prompt` field is new in P2.4's extended `TestResult` — it stores the task prompt. This is intentional (for reproducibility) but means the report contains the full prompt text. No security issue since prompts come from the trusted suite file.

**No API keys in schema**: Confirmed — neither `RunMetadata` nor `TestResult` have fields for API keys, tokens, or credentials. The `config` object is never stored in the report. This is good design.

#### 7. Supply Chain: yoker SDK Trust Boundary

The runner imports `yoker`, `yoker.events`, and uses `yoker.agent()`, `yoker.process()`. The trust boundary:

- **yoker-test** defines what to test (tasks, scorers, suite config)
- **yoker SDK** defines how to test (backend pipeline, event stream, tool execution)
- **Backend provider** (Ollama, OpenAI, etc.) defines the model and API

yoker-test trusts yoker to:
- Pass prompts to the backend correctly
- Report accurate token counts and latency via events
- Execute tools safely (when enabled)
- Handle API key storage (in yoker config, not in yoker-test)

**Risk**: If yoker SDK has a vulnerability (e.g., logs API keys, sends data to unintended endpoints), yoker-test inherits it. However, yoker is a co-developed project under the same control. The editable install (`../yoker`) means the developer is running their own yoker code.

**Assessment**: No action needed. The trust boundary is clean — yoker-test never handles API keys directly (they live in yoker config). The `config: Any` parameter passed to the runner is the yoker config object, which is used only for backend access, never serialized into the report.

#### 8. Sandboxing: code_execution Scorer

Covered in M1. The `code_execution` scorer is the only path where model-generated code runs. The runner's interaction is:
1. Runner calls `scorer(task, response)` — this is the standard scorer interface
2. The `code_execution` scorer extracts code from the response and `exec()`s it
3. The runner receives a `Score` result

The runner does not need to know about the sandbox — the scorer encapsulates it. However, the runner could add a safety layer by:
- Checking if any task uses `code_execution` scorer before running
- Printing a warning at suite start
- Allowing `--skip-code-execution` to skip those tasks

**Assessment**: The runner should be aware of `code_execution` tasks and warn. The scorer itself is the right place for sandbox improvements (M1).

---

### Recommendations (Prioritized)

1. **M1**: Add `--allow-code-execution` CLI flag and warning at suite load when `code_execution` tasks are present. ~15 lines of code across `cli.py`, `loader.py`, `runner.py`.
2. **M2**: Print warning at suite load when `!function` tags are present. ~5 lines in `loader.py`.
3. **L1**: Add `sanitize_error(msg: str) -> str` utility. Call before storing in `TestResult.error`. ~20 lines in a new `utils.py` or in `runner.py`.
4. **L2**: Add `asyncio.wait_for()` timeout wrapper in `EvalRunner.run()`. Add `task_timeout` to `SuiteConfig`. ~10 lines.
5. **L3**: Add configurable `inter_task_delay` to `SuiteConfig`. ~5 lines.
6. **L4**: Consider `include_messages` flag in `SuiteConfig` for report transcript control. Defer to P2.5.

---

### Positive Observations

- **No secrets in schema**: `RunMetadata` and `TestResult` contain no API keys, tokens, or credential fields. Clean design.
- **Config not serialized**: The yoker config object is never stored in `TestReport`. The `config: Any` parameter is used transiently.
- **SafeLoader for YAML**: `loader.py` subclasses `yaml.SafeLoader`, not `yaml.Loader` — prevents arbitrary YAML object construction.
- **Graceful degradation pattern**: Per-task error catching with score 0.0 and continuation is the right pattern for an evaluation tool.
- **`fetch_ollama_usage` catches all exceptions**: Returns `None` on failure, doesn't crash the suite. Good defensive coding.
- **`validate_suite()` exists**: Structural validation is already implemented and tested.
- **Restricted builtins attempt**: The `code_execution` scorer at least attempts restriction, even if bypassable. Shows security awareness.

---

### Security Findings Classification

| Finding | Classification | Action |
|---------|---------------|--------|
| M1: code_execution sandbox bypassable | Blocking | Add CLI opt-in flag + warning before P2.4 ships with code_execution support |
| M2: !function arbitrary import | Related | Add warning at load time, document trust model |
| L1: Error message leakage | Related | Add sanitize_error() utility in P2.4 |
| L2: No task timeout | Related | Add asyncio.wait_for() in EvalRunner |
| L3: No rate limiting | New | Add to backlog — operational, defer |
| L4: Message transcript exposure | New | Add to backlog — defer to P2.5 report work |

---

### Threat Model Summary (STRIDE)

| Category | Risk Level | Notes |
|----------|-----------|-------|
| **Spoofing** | N/A | No authentication in yoker-test; yoker config handles API auth |
| **Tampering** | Low | Suite files are trusted source code; `!function` is intentional |
| **Repudiation** | N/A | Not applicable to a CLI evaluation tool |
| **Information Disclosure** | Low | Error messages (L1), message transcripts (L4) — both mitigable |
| **Denial of Service** | Low | Resource exhaustion (L2, L3) against self, not a service |
| **Elevation of Privilege** | Medium | code_execution scorer (M1) — model code runs with dev privileges |