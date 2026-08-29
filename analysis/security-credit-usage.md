# Security Review: P2.5.10 — Ollama Credit Usage + Score-Per-Cost Ranking

**Date:** 2026-08-30
**Scope:** Security/privacy review of the P2.5.10 design (`analysis/credit-usage-design.md`),
research (`research/ollama-credit-usage.md`), and current code (`src/yoker_test/usage.py`).
Review only — no implementation.

---

## Executive Summary

The proposed credit-usage capture is sound from a security and privacy standpoint.
The API key flows through a narrow, in-memory path into a single hardcoded
HTTPS request, never through logs, error messages, or persisted results. The
design already avoids the two dangerous patterns found during review (settings-page
cookie scraping, and instantiating `OllamaBackend` which mutates
`os.environ["OLLAMA_API_KEY"]`). No blockers. Four small changes recommended,
all cheap: make "normalized snapshots only" an explicit invariant, record a
do-not-integrate decision for `/api/me`, add a 429/auth-failure circuit breaker,
and document a header-logging constraint in `usage.py`.

---

## 1. Credential Handling (Review Point 1)

### Flow

```
~/.yoker.toml or ./yoker.toml
  -> yoker Config (OllamaConfig.api_key, in-memory only)
  -> yoker_test.fetch_ollama_usage(config)
  -> httpx GET https://ollama.com/api/usage, Authorization: Bearer <key>
  -> response parsed -> fractions only
```

### Findings

| # | Check | Result |
|---|-------|--------|
| 1.1 | Key in logs | **No action needed.** No logging config anywhere in yoker-test; `usage.py` has none. Runner prints only task IDs/scores/errors to stderr. |
| 1.2 | Key in error messages | **No action needed.** `except Exception: return None` (usage.py:31-32) discards the exception — the Bearer key never reaches a traceback or printed message. Note: `str(exc)` from httpx contains the URL but not request headers, so no leak even if surfaced later. |
| 1.3 | Key in saved results | **No action needed.** `TestReport`/`RunMetadata` serialize suite/model/provider/version/timestamp and metrics only. Config is never serialized; the usage fetch response is parsed down to fractions before it touches schema objects. |
| 1.4 | Key in verbose output (P2.5.1 `--verbose`) | **No action needed.** Verbose prints prompt/response/evaluation detail — no config surfaces. |
| 1.5 | Redirect leak | **No action needed.** httpx does not follow redirects by default (`follow_redirects=False`); even a malicious redirect could not receive the header. URL is HTTPS-verified by default. |
| 1.6 | Key copies in environment | **No action needed — positive observation.** The design (§3.5) explicitly rejects reusing `OllamaBackend.fetch_usage()`, which requires instantiating the backend and would copy the key into `os.environ["OLLAMA_API_KEY"]`. The duplicate HTTP call is the security-correct trade-off here. |
| 1.7 | Host pinning | **No action needed (keep as-is).** The usage URL is hardcoded `https://ollama.com/api/usage` and independent of the configurable inference `base_url`. Do not later make the usage endpoint configurable from config — a configurable host would let a misconfigured/untrusted config exfiltrate the key. Keep it pinned. |

### Low — F2: Logging constraint for the future (Related)

The silent `return None` is good for security but poor for diagnosability. When
someone eventually adds error logging (the temptation is real and reasonable),
the dangerous trap is logging the *request*: `exc.request.headers` carries the
Bearer key, and httpx `HTTPStatusError.request` retains it.

**Recommendation:** add one line to the `fetch_ollama_usage_raw` docstring now,
while the file is being touched anyway:

```python
# NOTE on failures: str(exc) is safe (URL only), but NEVER log or serialize
# exc.request — its headers contain the authorization Bearer key.
```

No code change, just the constraint on record.

---

## 2. Saved-Results Sensitivity (Review Point 2)

Context: results land in `results/` (P2.5.2 will make this the default) and the
owner intends to publish figures in a blog post / public league tables.

### What gets persisted, what it reveals

| Field | Sensitivity | Verdict |
|-------|-------------|---------|
| `usage_delta` (session/weekly fractions) | Relative account-quota consumption. No identity, no absolute allowance size. | **Safe to publish.** |
| `requests_delta` (per-model request count) | Exact API-call volume for the *evaluated model only*. | **Safe to publish.** |
| `usage_before` / `usage_after` (raw fractions) | Point-in-time absolute account quota state — reveals how busy the account was at run time, including non-run usage. | **Low.** Mild footprint disclosure; acceptable. Strip columns if publishing raw YAML. |
| `extra_usage_cost_delta` (USD string → float) | Paid-balance spend per run. Publishable, but reveals the account draws from extra usage. | **Low.** Owner's call for the blog post; not a credential-adjacent value. |
| `usage_note` (reset annotation + raw values) | Same class as usage_before/after. | **Low.** No action. |

No PII is persisted anywhere in the planned fields: no email, name, plan tier,
key material, or account IDs.

### Medium — F3: Keep normalized snapshots only — make it an invariant (Related)

The design's `_snapshot_usage` filters the API response down to
`{"session", "weekly", "requests", "extra_cost"}` for **this run's model**.
This matters: the raw `/api/usage` body contains `limits.*.models[]` for **all**
models the account used in the window. Persisting the raw body would disclose
the maintainer's unrelated account activity (other models used in other
projects that day) into every saved report — exactly the kind of file that will
be shared publicly for the blog post and league tables.

**Recommendation:** treat "never serialize the raw API response" as an explicit
invariant, not an implementation detail:

1. One sentence in the design doc + `usage.py` docstring: raw response stays in
   memory; only the normalized snapshot may reach schema fields.
2. A small negative test asserting no field of `TestReport.to_dict()` can carry
   an unknown per-model list (the existing `_filter_fields` load path already
   enforces the schema-side half; a round-trip test on captured fields covers
   the rest). The design's §6.1 schema tests nearly do this — extend the
   round-trip test to assert the raw key set never grows beyond the documented
   fields.

### Medium — F4: Never integrate `POST /api/me` (New — record the decision)

The research (§2.2) notes `/api/me` returns plan tier — "useful only to annotate
a report with the plan tier". It also returns **email, name, subscription
period, customer/subscription IDs**. The current design does not use it. Keep
it that way: annotating reports with plan tier is a slippery slope toward
account metadata in files destined for public sharing.

**Recommendation:** record an explicit out-of-scope decision in the design doc:
"P2.5.10 does not call `/api/me`; no account-identifying fields in reports."
If plan tier is ever genuinely needed, it is owner-opt-in, display-only, and
never persisted.

### Low — F5: Public-sharing guidance (New)

For the blog post / league tables: usage deltas and request counts are safe;
`usage_before/after`, `extra_usage_cost_delta`, and `usage_note` reveal account
footprint and paid-balance usage. A one-line note in the report README (or when
extracting figures for the post) is sufficient.

---

## 3. Fetch Gate Correctness (Review Point 3)

### Findings

| # | Check | Result |
|---|-------|--------|
| 3.1 | Cross-provider credential leakage | **Gate fixes it.** Current `usage.py` gates only on "ollama config + key present" — a stray ollama key alongside an openai backend would fire the fetch. The design's `_snapshot_usage` requires `provider == "ollama"` at the call site with the key check as inner layer. Endorse as specced. |
| 3.2 | Key sent to non-ollama host | **No action needed.** URL is a hardcoded literal; only ollama.com can ever receive the key regardless of gate state. |
| 3.3 | Misleading data attribution | **Handled, one note — see F10.** Window-reset and unavailability cases become `None`/partial dict + `usage_note`, so reports degrade honestly. |
| 3.4 | Zero-call verification | **Covered by design.** §6.2's `make_mock_config` change (`backend.ollama = None`) plus the §6.1 zero-calls mock assert is the right test — it prevents both misleading data and accidental real HTTP from unit tests. |

### Info — F10: Stale-snapshot chaining misattributes usage after a fetch failure (Related — one docstring line)

The design chains `test_before = after if after is not None else None`. If one
"after" fetch fails, `after` keeps the last good snapshot, so the *next* test's
delta silently includes the failed test's inference usage. This is a data
quality / fairness-of-ranking issue, not a vulnerability (no leak, no
credential exposure). One sentence in the `TestResult.usage_delta` docstring —
"deltas are best-effort; a failed snapshot shifts adjacent deltas" — prevents
future misreading of league-table numbers.

---

## 4. Rate-Limiting / Politeness (Review Point 4)

### Findings

| # | Check | Result |
|---|-------|--------|
| 4.1 | Volume | ~2 metadata GETs per executed test (~180 for the default 30×3 suite), each naturally spaced by the test's own duration (seconds at minimum), 10s timeout. Bounded per run; no daemon behavior. The edge-chaining trick (next before = previous after) means no extra aggregate calls. |
| 4.2 | Quota impact | Metadata-only; does not consume inference quota (research §2.5, multiple confirmations). |
| 4.3 | ToS | Standard API-key auth against ollama.com = access *with* permission (ToS §4). Endpoint is undocumented-but-maintainer-blessed; shape change degrades to `None`. Acceptable. |
| 4.4 | Failure-loop abuse | **See F8.** |

### Low — F8: No circuit breaker on repeated failures (Related)

On persistent failure (e.g. HTTP 429, or a shape change returning 4xx), the
design keeps issuing 2 calls per test for the whole run — ~180 pointless
requests in the worst case, impolite to a service whose goodwill the project
relies on.

**Recommendation:** one minimal circuit breaker in the capture helper: if a
snapshot fetch fails with an HTTP status (esp. 429/401/403), stop fetching for
the remainder of the run (set a flag; subsequent snapshots return `None`,
fields stay `None`, note already says "usage API unavailable"). No config, no
class — a few lines in `_snapshot_usage`. Network blips can keep retrying; only
server-declared rejection trips the breaker. Document the call budget
(~2×N per run) in the `usage.py` docstring so future per-test granularity
changes are made consciously.

---

## 5. Research Proposal Items Reviewed on Security Grounds (Review Point 5)

| Proposal item | Security verdict |
|---|---|
| Cookie-scraping the settings page (§2.4.1) | **Reject — keep rejected permanently.** The `__Secure-session` browser cookie is a broader credential than the API key (full account session); storing/persisting it in a framework, and HTML-parsing an unversioned page, expands blast radius for zero data the API doesn't approximate. Research already recommends against; record as a hard "no". |
| `POST /api/me` for plan-tier annotation (§2.2) | **Reject** (see F4) — email/name/subscription IDs adjacent to public result files. |
| Persisting richer raw data (§5(b).3) | **Accept only as normalized** (see F3) — raw response body must never be persisted. |
| Silent `None` degradation | **Accept** — security-positive (no error spam, no exception content reaching output). Pair with the F2 docstring note. |
| Reusing `OllamaBackend.fetch_usage()` (§4.1) | **Correctly rejected** — instantiation mutates `os.environ["OLLAMA_API_KEY"]` (extra key copy, process-global). Local duplication is the safer shape, and it keeps the 10s timeout behavior local and auditable. |
| Polling `/api/usage` at 2×N per run (§2.5) | **Accept** as reasonable use; add the F8 breaker so failure modes stay polite too. |

---

## Security Findings Classification

| Finding | Severity | Classification | Action |
|---------|----------|----------------|--------|
| F2: Header-logging constraint undocumented | Low | Related | One docstring line in `usage.py` during implementation |
| F3: Raw API response must never be persisted (other models' counts) | Medium | Related | Make normalized-snapshot-only an explicit invariant + round-trip test |
| F4: `/api/me` integration risk (email/IDs near public files) | Medium | New | Record do-not-integrate decision in design doc |
| F8: No circuit breaker on 429/40x | Low | Related | Stop per-run snapshot fetching on server-declared rejection |
| F10: Stale-snapshot usage misattribution (data quality) | Info | Related | One docstring sentence on delta reliability |

## Explicitly Verified — No Action Needed

- Hardcoded HTTPS URL, httpx default TLS verification and no-redirect behavior.
- Key never logged, printed, or serialized (silent `None` degradation).
- No PII in any planned persisted field.
- `_filter_fields` load path keeps old report files loadable — no schema hazard.
- Test-hygiene fix (`backend.ollama = None` in `make_mock_config`) prevents
  mock-truthy accidental real HTTP calls.

## Positive Observations

1. The design's rejection of `OllamaBackend.fetch_usage()` is the right
   security call — it avoids environment-wide key duplication.
2. Normalized snapshots only, keyed to the evaluated model, is a privacy filter
   that most usage-tracking tools skip.
3. Honest degradation (`None` + `usage_note`) prevents misleading cost claims
   in public rankings.
4. The gate-in-one-place pattern (both provider and key checks in
   `_snapshot_usage`) makes bypass difficult by construction.

---

## Verdict

**Proceed-with-changes** — none blocking:

1. **F3 (invariant):** document "raw API response is never persisted; only the
   normalized per-model snapshot" in the design and `usage.py`, back it with a
   round-trip field test.
2. **F4 (decision):** record in the design doc that `/api/me` is out of scope
   and no account-identifying fields may enter reports.
3. **F8 (politeness):** add the minimal stop-on-429/401/403 breaker for the
   remainder of a run; note the ~2×N call budget in the docstring.
4. **F2 + F10 (docstrings):** never-log-request-headers constraint and one
   sentence on stale-snapshot attribution, both in `usage.py`/
   `TestResult.usage_delta` docstrings.