# Research: Ollama Credit/Usage Data for Cloud Models (P2.5.10a)

**Date:** 2026-08-30
**Status:** Research only — no implementation
**Related:** TODO.md P2.5.10, `src/yoker_test/usage.py`, `src/yoker_test/runner.py`, `src/yoker_test/report.py`

---

## 1. Executive Summary

| Question | Answer |
|---|---|
| What credit/usage data exists? | Aggregate quota fractions (`limits.session.usage`, `limits.weekly.usage`), per-model **request counts**, extra-usage `activity.cost` (USD string). No tokens, no per-model credit weights. |
| How to query it? | `GET https://ollama.com/api/usage` with `Authorization: Bearer <API key>`. Undocumented but stable; multiple third-party tools depend on it. |
| Auth requirements? | An Ollama API key (`ollama.com/settings/keys`). Session-cookie scraping also exists but is brittle and not API-key based — avoid. |
| Per-request/per-test credit accounting? | **No.** Response bodies and headers of chat/generate calls carry token counts only — no account-level quota data on any inference response. |
| Recommended capture? | **Real: aggregate snapshot delta** (before/after the run). Per-test: request-count delta (real, integer) + token-based estimation (proxy). Per-test quota-fraction deltas are technically possible but quantized/noisy. |
| Current wiring state? | `fetch_ollama_usage` is **dead code** in the suite flow — no call sites. `OverallSummary.usage_delta` is always `None`, so the "Usage Δ" line and the ranking's usage column always show empty/N/A. |

---

## 2. What Ollama exposes today

### 2.1 `GET https://ollama.com/api/usage` — the primary source

Undocumented-but-stable account usage endpoint for cloud API keys. Authentication is
the same API key used for inference:

```bash
curl -H "Authorization: Bearer $OLLAMA_API_KEY" https://ollama.com/api/usage
```

Live response shape (confirmed from multiple independent sources, 2026-07/08):

```json
{
  "activity": {
    "cost": "0.00000",
    "period": {
      "type": "last_4_weeks",
      "starting_at": "2026-07-06T00:00:00Z",
      "ending_at": "2026-07-29T12:45:50Z"
    },
    "models": []
  },
  "limits": {
    "session": {
      "usage": 0.046,
      "models": [
        { "name": "glm-5.2", "request_count": 34 },
        { "name": "minimax-m3", "request_count": 2 }
      ]
    },
    "weekly": {
      "usage": 0.051,
      "models": [
        { "name": "glm-5.2", "request_count": 254 },
        { "name": "minimax-m3", "request_count": 107 }
      ]
    }
  }
}
```

Field semantics:

| Field | Meaning |
|---|---|
| `limits.session.usage` | Consumed fraction (0..1) of the **5-hour session window** allowance |
| `limits.weekly.usage` | Consumed fraction (0..1) of the **7-day weekly window** allowance |
| `limits.<w>.models[]` | Per-model **request counts** within that window (names without `:cloud` suffix) |
| `activity.cost` | Extra-usage (paid balance) spend in **USD as a string**, over a rolling 4-week period |
| `activity.period` | The 4-week activity window |

Important caveats:

- **No quota metadata on inference calls.** `/api/chat`, `/api/generate`,
  `/api/embed` return only token counts (`prompt_eval_count`, `eval_count`) —
  no account-level quota in body or headers (ollama/ollama#15663).
- **No reset timestamps** in the response. Resets are however deterministic and
  globally aligned: session every 5 hours (epoch-aligned), weekly every 7 days
  (computable client-side; see sources).
- **Request counts ≠ credits.** Credit consumption is model-dependent
  (usage levels 1–4 × input/cached-input/output tokens), so request_count alone
  cannot rank models by cost — but it *is* an exact integer measure of API call
  volume attributable to a model within a window.
- The endpoint is **undocumented**; the official `docs.ollama.com/api/usage`
  page documents the *per-request stats schema* of chat/generate responses (a
  naming trap). Ollama staff have indicated usage API changes are pending
  (Discord, Aug 2026) — the shape may evolve; parse defensively.

### 2.2 `POST https://ollama.com/api/me` — account metadata

```bash
curl -s -X POST \
  -H "Authorization: Bearer $OLLAMA_API_KEY" \
  -H "Content-Type: application/json" \
  https://ollama.com/api/me
```

Returns plan (`"pro"`), email, name, subscription period start/end, customer/subscription
IDs. **No usage percentages.** Useful only to annotate a report with the plan tier.

### 2.3 What does NOT exist

Verified gaps (multiple community confirmations, open/closed feature requests):

- **No quota headers on inference calls.** Feature request ollama/ollama#15663
  (requesting `X-Ollama-Quota-*` headers or body fields) was closed without
  implementation.
- **No per-model credit/token consumption.** `/api/usage` gives request counts
  only; the settings page (cookie-authenticated) gives per-model usage-bar
  *shares*, but no API surface exposes per-model credits.
- **No per-request credit accounting** — there is no way to ask "how much quota
  did request X consume"; only before/after aggregate deltas.
- **No per-API-key usage breakdown** (relevant only if multiple keys are used;
  yoker-test uses one key).

### 2.4 Pricing model context (why per-model weights matter)

Ollama does not publish fixed token allowances. Cloud usage is measured by the
model's **usage level** × **input, cached-input, and output tokens** processed;
models carry levels 1 (light, e.g. `gpt-oss:20b`) through 4 (extra heavy, e.g.
`deepseek-v4-pro`). Allowances reset on a 5-hour session cycle and 7-day weekly
cycle. Pro/Max accounts may hold an **extra usage balance**: inference draws from
included limits first, then from the extra balance at the model's published
per-token rates (e.g. Kimi K3: $3/M input, $0.30/M cached input, $15/M output —
explicit per-token rates). Consequences for us:

- The quota fraction is the only "compute consumed" signal during the
  included-limit phase.
- `activity.cost` is the only monetary signal during the extra-balance phase.
- A per-token pricing path exists per model on model pages, which is why the
  deferred P2.6 pricing work remains viable later.

### 2.4.1 The dashboard scraping path (not recommended)

The authenticated settings page (`ollama.com/settings`) renders session %, weekly
%, reset countdown, and per-model usage-bar shares — richer than `/api/usage`.
But it requires the `__Secure-session` **browser cookie** (not the API key),
breaks on markup changes and session expiry, and sits in ToS gray territory.
Several third-party monitors use it as primary source with `/api/usage` as
API-key fallback. For yoker-test — a framework — the API-key-only path is the
defensible choice; the cookie path should only ever be an optional, explicit
opt-in (not recommended).

### 2.5 Terms-of-service considerations

- Ollama ToS §4 prohibits "automated means to access our services **without
  permission**". Using the standard `OLLAMA_API_KEY` credential against
  `ollama.com` API endpoints is *with* permission — it is the documented cloud
  API credential for that host (docs/Cloud: API-key auth for ollama.com as host).
- `/api/usage` is undocumented, but Ollama's own maintainer posted the exact
  curl against it as the resolution to the community's usage-tracking request
  (issue #12532), and staff indicated more usage API is pending. Community
  tools depend on it. Risk: shape may change without notice since it is not a
  documented contract — degrade gracefully to `None` (as `usage.py` already
  does).
- Cookie scraping of the settings page is the riskier pattern (session cookie
  is not an API credential; HTML parsing is a de-facto contract with no
  stability). Recommendation: do not build on it.
- Polling `/api/usage` is metadata-only and does not consume inference quota;
  community tools poll every 5–30 minutes. Our snapshot pattern (2 fetches per
  run, ~2×N per suite with per-test capture) is well within reasonable use.

---

## 3. Per-test vs aggregate credit accounting

Per-test **real** credit accounting does not exist upstream. Four capture
strategies, in decreasing order of fidelity-to-effort ratio:

### 3.1 Aggregate snapshot delta (recommended, real data)

Snapshot `GET /api/usage` immediately before the first task and immediately
after the last task; `delta = after - before` per window. This measures what
the eval consumed from the included allowance (assuming no other significant
usage concurrent with the run):

```python
usage_before = await fetch_ollama_usage(config)   # {"session": 0.046, "weekly": 0.051}
# ... run all tasks x repeats ...
usage_after = await fetch_ollama_usage(config)    # {"session": 0.051, "weekly": 0.052}
# session delta = 0.005 -> 0.5% of the 5h allowance consumed by this run
```

Error modes:

- **Window reset mid-run** (5h/7d boundary crossed): `after < before` for the
  affected window → delta negative/garbage. Mitigation: set `None` (report
  "unavailable") and optionally record raw before/after for annotation.
- **Concurrent usage by other clients** inflates the delta. Acceptable for
  single-account benchmarking; note in report.
- **Server-side quantization** observed at 3 decimals (e.g. 0.046): a small
  suite's delta may round to 0.000. Weekly is the more stable signal for short
  runs; session is meaningful for long runs / heavy models.

### 3.2 Per-model request-count delta (real, integer, per-run and per-test)

`limits.weekly.models[].request_count` for the evaluated model, delta
before/after = the exact number of API requests attributed to that model.
Yoker-test evaluates one model per run, so attribution is unambiguous. Not a
credit metric, but an exact, noise-free activity metric, pairable with token
counts — and it can equally be polled per test (integer deltas survive
quantization).

### 3.3 Per-test snapshot delta (feasible, noisy)

Polling before/after each test (2 extra HTTP calls per test, *outside the timed
section* so latency metrics are unaffected) yields per-test quota deltas, but:
deltas are quantized at the server's rounding precision (a single light-model
request can round to 0.000), and any in-flight reset or out-of-band usage
poisons individual test deltas. Verdict: **possible but low signal per test**;
the request-count delta (3.2) is the better per-test real metric.

### 3.4 Token-based estimation per test (already collected, proxy)

`StatsCollector` already captures exact `tokens_in` / `tokens_out` per test
from `TurnEndEvent`. Combined with each model's published usage level and/or
extra-usage per-token rates this yields a **relative per-test cost estimate**.
It is an estimate, not a measured credit value, and token-based pricing was
explicitly deferred (TODO.md P2.6 owner decision) — but as a fallback/secondary
per-test metric it needs zero API calls and already lives in `TestResult`.
Caveat: Ollama meters input + cached input + output tokens; our estimator sees
only in/out (cached-input share unknown) — another reason it stays an estimate.

**Recommended mix:** aggregate quota-fraction delta (3.1) as the run-level real
cost metric + per-model request-count delta (3.2, per-run and optionally
per-test) as real activity + existing per-test tokens (3.4) as the estimation
fallback. No cookie scraping.

---

## 4. Current wiring evaluation

### 4.1 `usage.py::fetch_ollama_usage` (extracted P1.3)

```python
async def fetch_ollama_usage(config: Any) -> dict[str, float] | None:
  # GET https://ollama.com/api/usage, Bearer auth from config.backend.ollama.api_key
  # extracts limits.session.usage / limits.weekly.usage (0..1 fractions)
  # returns None on missing key or ANY exception (silent degradation)
```

Findings:

- Endpoint, auth, and extraction are correct and match the verified response
  shape (§2.1). The 10 s timeout and silent `None` degradation are appropriate.
- It **discards** `limits.*.models[].request_count` and `activity.*` — data we
  now want (§3.2, extra-usage cost).
- Duplication: yoker's `OllamaBackend.fetch_usage()`
  (`../yoker/src/yoker/backends/ollama.py:66`) returns the raw response dict;
  `usage.py` re-implements the HTTP call rather than reusing it. Acceptable for
  testability (mocked httpx, no backend instantiation required) but a decision
  worth documenting.

### 4.2 Where it is (not) wired

Call-site audit across `cli.py`, `config.py`, `runner.py`, `report.py`:

- **No call sites exist** — `fetch_ollama_usage` is imported nowhere.
- `EvalRunner.run()` (`runner.py`, lines ~197–200) calls
  `summarize_overall(results, summary, self._weights)`; the `usage_delta`
  parameter defaults to `None`, so `OverallSummary.usage_delta` is **always
  `None`** in suite runs.
- Consequently `format_console_report` never prints the `Usage Δ` line
  (`report.py:318–320`) and `format_quality_ranking` renders `"N/A"` in the
  usage column (`report.py:366–368`) — the "quality for usage" primary goal is
  currently unpopulated.
- Legacy single-task path: `print_report` + `compute_composite`
  (`report.py:17–113`, P1.5 backward compatibility) consume before/after usage
  snapshots and feed `session_delta` into the composite cost score — but
  nothing calls `print_report` anymore (`__main__.py` → `cli.py` →
  `format_console_report` only).

### 4.3 Serialization

`OverallSummary.usage_delta: dict[str, float] | None` round-trips correctly
through `to_yaml()` / `to_json()` / `from_dict()` (`asdict` for dump;
`_filter_fields` on load ignores unknown keys → backward compatible when new
fields are added later).

---

## 5. Required changes (research conclusions — not implemented)

### (a) Per-test credit usage

1. **New fields on `TestResult`** (schema.py), all optional with `None`
   defaults: e.g. `usage_session_delta: float | None`,
   `usage_weekly_delta: float | None`, `requests_delta: int | None` — or a
   single `usage_delta: dict[str, float] | None` mirroring `OverallSummary`.
2. **Snapshot points**: capture before and after each `_execute_once` from
   `EvalRunner.run`'s loop in `runner.py` — *outside* the timed section (before
   `t0` / after wall-clock capture) so latency and TTFT metrics are untouched.
   2 HTTP calls per test; consider polling sparsely (e.g. per task, not per
   repeat) to balance precision vs request volume.
3. **Semantics**: treat per-test quota-fraction deltas as noisy estimates
   (§3.3); the reliable per-test real metric is the per-model `request_count`
   delta (integer). Persist raw before/after snapshots only if quantization
   auditing is desired; deltas alone keep reports small.
4. Optional: per-test token-based usage estimate from existing
   `tokens_in`/`tokens_out` × model usage level — deferred-pricing territory;
   keep out of scope for P2.5.10b, revisit under P2.5.10c formula work.

### (b) Aggregate credit usage

1. **Wire the existing function**: in `EvalRunner.run()` (or `evaluate()` in
   config.py, which owns config/lifecycle): snapshot once before the task
   loop, once after; compute `{"session": Δ, "weekly": Δ}`; pass as
   `usage_delta=` to `summarize_overall` — the parameter and all report
   rendering already exist.
2. **Negative delta (window reset mid-run)** → set `usage_delta = None` plus
   an annotation field (e.g. `usage_note: str | None`) so the ranking shows
   N/A honestly instead of a bogus negative cost.
3. **Persist richer raw data**: extend `OverallSummary` with e.g.
   `usage_before: dict[str, float] | None`, `usage_after: ...`,
   `requests_delta: int | None`, `extra_usage_cost_delta: float | None`
   (from `activity.cost`, applies when drawing from extra balance). Requires
   extending `fetch_ollama_usage` (or adding `fetch_ollama_usage_raw`) to
   surface `limits.*.models[].request_count` and `activity.cost`.
4. **Provider gating**: only attempt when `config.backend.provider == "ollama"`
   (and an API key is set). Current code checks only the key — with an
   openai/anthropic backend a stray ollama key would fetch usage of the wrong
   provider; an explicit check at the call site avoids that.
5. **Report/ranking**: no rendering changes strictly needed — but decide
   whether the ranking table should show the **weekly** delta (7-day
   stability, better for model-to-model comparison) instead of/in addition to
   the session delta.

---

## 6. Recommendation Summary

- Real, sanctioned credit data = two aggregate quota fractions + per-model
  request counts + extra-usage cost, via one undocumented-but-stable GET with
  the standard API key.
- Capture **aggregate delta** around each eval run (real); capture
  **request-count delta** for exact per-test/per-run activity (real); keep
  tokens as the per-test estimator (already collected); **no cookie scraping**.
- Minimum viable change to fill the ranking's cost column: snapshot before/
  after in `EvalRunner.run` + pass `usage_delta` to `summarize_overall` +
  provider gate; report code already consumes it.

## 7. Sources

- ollama/ollama issue #12532 "Cloud usage stats" — live `/api/usage` response
  body (Jannled, 2026-07-29); maintainer-confirmed endpoint; reset-time
  derivation; per-model request-count limitation:
  https://github.com/ollama/ollama/issues/12532
- ollama/ollama issue #15663 "Expose account quota/usage details via Ollama
  Cloud API" — confirms no quota headers/fields on inference responses:
  https://github.com/ollama/ollama/issues/15663
- ollama/ollama issue #15132 "Account Usage API Endpoint" (closed dup):
  https://github.com/ollama/ollama/issues/15132
- oh-my-pi PR #10101 — independent implementation mapping `limits.session` /
  `limits.weekly` (0..1 fractions, 5h/7d windows, per-model request counts):
  https://github.com/can1357/oh-my-pi/pull/10101
- dsh-usage-stats PR #55 — independent adapter, same response shape, ratio
  clamping and error mapping:
  https://github.com/Ychris12138/dsh-usage-stats/pull/55
- Kosello/ollama-cloud-watch — settings-page vs `/api/usage` capability
  comparison (cookie path gives per-model usage-bar shares; the API does not):
  https://github.com/Kosello/ollama-cloud-watch
- Ollama pricing FAQ — 5h/7d reset cycles, usage-level metering
  (input/cached-input/output tokens), extra-usage balance, Kimi K3 rates:
  https://ollama.com/pricing
- Ollama cloud docs — API-key auth for ollama.com as host; the `/api/usage`
  docs page (per-request stats schema, not account usage):
  https://github.com/ollama/ollama/blob/main/docs/cloud.mdx and
  https://docs.ollama.com/api/usage
- Ollama Terms of Service §4 (automated access):
  https://ollama.com/terms
- `POST /api/me` account fields (jwh9456 comment in issue #12532)
- Local verification: `src/yoker_test/usage.py`, `runner.py`, `report.py`,
  `schema.py` (call-site audit); `../yoker/src/yoker/backends/ollama.py:66`
  (`OllamaBackend.fetch_usage`); TODO.md P2.5.10 / P2.6 (owner decisions).