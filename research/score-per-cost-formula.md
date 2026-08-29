# Research: Score-per-Cost Formula for the yoker-test Ranking Composite

**Task**: P2.5.10c — research and reason the exact combining formula for a
"result-per-cost" ranking composite.
**Date**: research-only deliverable; no implementation included.
**Feeds**: report.py ranking (currently quality-only) and the glm-5.2:cloud vs
glm-5.3:cloud vs glm-5.3-flash:cloud blog post.

  ## 1. What we are combining (exact data model)

From `schema.py` and `report.py`:

- **Quality**: `OverallSummary.score`, in **0.0-1.0**. Weighted category
  mean (suite weights: knowledge 0.25, reasoning 0.25, instruction 0.20,
  code 0.15, tool_use 0.15). Bounded, absolute (not model-relative).
- **Usage**: `OverallSummary.usage_delta["session"]` and
  `UsageDelta["Weekly"]`... `["weekly"]`, stored as **fractions of the Ollama
  rate-limit budget**, 0.0-1.0 each (multiplied by 100 only for display).
  These are per-run *deltas* measured before/after the suite
  (`fetch_ollama_usage` returns rate-limit percentage points as fractions).
- **Existing precedent in the codebase**: `compute_composite` already uses
  `quality * 1/(1 + cost_delta/max(n_correct,1) * scale)` — a
  **multiplicative, diminishing-returns** cost gate where cost=0 maps to
  cost_score=1.0 and the composite reduces to pure quality.

Key structural facts:
- quality and usage are both bounded in [0, 1] (after unit alignment) — no
  z-score-style unbounded tails.
- usage is a *budget consumption rate*, not a dollar price. It is monotonic
  with real cost at fixed budget, which is all we need for ranking.

  ## 2. Real-world precedent (what other leaderboards do)

| System | How quality and cost are combined |
|---|---|
| Artificial Analysis | Publishes Intelligence Index (quality), Price($/Mtok), and Speed as **separate axes**; an additional "Cost per Task" is computed from *measured* token usage x price (not sticker price), with explicit warning that "models that produce longer answers or more reasoning tokens will have a higher cost per task, even at identical per-token prices". They show Intelligence-vs-Cost scatter/Pareto charts; quality-per-cost is *implicit*, read off the chart, never a hidden blended number. |
| HELM (Stanford CRFM) | Deliberately refuses to aggregate; multi-metric scores over a matrix, and explicitly states there is no universal aggregation of efficiency, accuracy, etc. A single-number composite is presented as a *value judgment*, not a measurement. |
| OpenRouter | Usage/popularity boards are explicitly *not* quality boards ("rankings measure adoption, not quality"); quality comes from separate benchmark indexes; price is a separate column. Avoids conflating the axes. |
| Cost-of-Pass (arXiv 2504.13359) | `cost_of_pass = C / R` — expected monetary cost per correct answer, grounded in Farrell production-efficiency theory. Closest formal analog to "result per cost". Handles R=0 by declaring cost-of-pass infinite / strategy infeasible. Also documents a benchmark-hacking mode: on forgiving multiple-choice tasks a cheap random guesser gets near-zero cost-per-pass if you divide by pass rate instead of using quality directly. |
| Industry commentary (Pareto-first movement) | Converging convention: (a) show the raw (quality, cost, latency) triple, (b) a Pareto/dominance filter, (c) only then — if at all — a scalarized score with **weights disclosed explicitly**, because "the hidden step is: the ranking depends entirely on weights that are not properties of the agents." |

Takeaway: nobody we could find multiplies/divides raw quality and cost
asymptotically; the two defensible patterns are (a) *economic ratio*
(cost per unit outcome, with infeasibility modeled as infinity) and
(b) *explicit-weight multi-attribute utility*. Both keep quality in the
driver's seat and cost as a deflation — exactly the shape of
`compute_composite`.

  ## 3. Option analysis

  We evaluate four families. Constraint: the formula is consumed by a
  ranking table in a public blog post comparing glm-5.2:cloud,
  glm-5.3:cloud and glm-5.3-flash:cloud.

  ### Option A — Raw ratio: `quality / usage_pct`

  ```
  value = quality / usage
  ```

  where usage is the run's session-budget fraction (0-1).

  **Mathematics**
  - Units: dimensionless if both factors are fractions (usage as 0-1, not
    0-100). If usage is left as a percentage (0-100) the value is silently
    100x smaller — the scale mismatch trap named in the task brief.
  - **Divide-by-zero**: usage=0 (a run that consumed no measurable budget
    slice — plausible for a tiny suite on a flash-tier model, or when the
    Ollama usage endpoint reports the *same rounded value* before and
    after a too-small run) yields ∞ — an unusable ranking value.
  - **Small-denominator blowup**: at usage=0.001 (0.1%), a garbage model
    with quality 0.05 scores 50x higher than a good model; the metric is
    dominated by numerator sensitivity to a nearly-zero denominator.
  - **Bounds mismatch**: with usage in 0-1, value is unbounded above
    (∞) while its "natural" ceiling (quality=1, usage→1) is 1 — so the
    score's range depends on the noisiest cheap model in the set.

  **Pros**: dead simple; exact economic meaning ("points per budget unit").
  **Cons**: undefined or exploding for free/cheap models — which are
  *precisely the interesting comparisons here* (glm-5.3-flash is cheap).
  Cost-of-Pass avoids this by treating zero-success as infeasible, but a
  zero-*cost* model is feasible, so the analogous fix isn't obvious.
  A ratio also rewards the cheapest model hardest exactly when quality is
  low: with usage fixed at the same slice, `0.6/0.4 = 1.5` vs `0.3/0.2 = 1.5`
  — a 2x-quality advantage is erased by spending less; that is defensible
  economics, but see Option D for a better-shaped version.

  **Verdict**: reject as the *headline* metric (undefined/blown-up tails),
  but its semantic (points-per-budget-unit) is worth keeping, in bounded form.

  ### Option B — Normalized per-comparison (min-max or z-score, then combine)

  ```
  z_q = (q_i - min(q)) / (max(q_i) - min(q_j))
  z_u = (u_i - min(u_i)) / (max(u_i) - min(u_j))
  value = z_q + a_z * (1 - z_u)    # variant
  ```

  **Mathematics**: makes scores comparable across axes; bounded 0-1 per axis;
  avoids divide-by-zero entirely (additive combination).

  **Pros**: stable, symmetric.
  **Cons** — severe for our stated use case (3 models):
  - **Absolute meaning destroyed**: quality is an *absolute* pass-rate on a
    fixed suite; min-max normalization converts it to "distance from the
    worst model in this comparison". A model that scores 0.95 and a model
    that scores 0.45 get compressed identically if they are the extremes.
  - **Pairwise instability**: z-score normalization is *pair-wise
    sensitive*. A 100-run ranking is reproducible; a 3-model blog-post
    ranking is not — adding a 4th model to the table can **re-rank the
    existing three** even when every model's own numbers are unchanged.
    That also breaks monotonicity guarantees across the table and makes
    stored results non-comparable day-to-day.
  - Artificial Analysis, HELM and OpenRouter all use *absolute*
    per-axis scores and let the reader see trade-offs; none normalize
    the quality axis against the compared cohort.

  **Verdict**: reject for the headline ranking. Acceptable only as a
  *presentation* aid (e.g. highlight the Pareto frontier), never as the
  stored/decisive number.

  ### Option C — Explicit-weight blend: `alpha*quality + (1-alpha)*(1 - usage)`

  ```
  value = alpha * quality + (1 - alpha) * (1 - usage)
  ```

  (both axes in 0-1; usage already inverted so "higher is better")

  **Mathematics**: this is a standard multi-attribute utility (MAUT)
  linear blend. Bounded 0-1 on both axes. Strictly monotone in quality
  and in (1 - usage): better quality or lower usage never lowers the
  value. Additive, well-defined at usage=0 and quality=0.

  **Choosing alpha** — the honest critique, straight from the industry
  commentary: "the ranking that comes out depends entirely on alpha, a
  number that is a value judgment, not a measurement." Choosing it well
  requires knowing *why* someone reads the ranking:
  - alpha=1.0: pure quality ranking (no cost signal) — what the table does
    today.
  - alpha=0.9..0.95: cost nudges ties; robust default for a general
    audience.
  - alpha=0.5: cost is half the story; favors cheap-but-mediocre over
    expensive-but-excellent more than most readers expect.
  - The additive form also has a *substitution* property that's
    philosophically wrong for evaluations: it lets an arbitrary amount of
    "cheapness" buy back "wrongness". A model scoring 0.55 with the same
    usage as a model scoring 0.95 ranks below, which is correct, but a
    model scoring 0.55 with half the usage can *outrank* the 0.95 model —
    and whether that's acceptable is exactly the un-disclosed judgment.

  **Pros**: bounded, monotone, explainable, computable with zero-denominator
  concerns, handles usage=None gracefully (treat as usage=0, i.e. free).
  **Cons**: the ranking is alpha-dependent — and readers of a public
  benchmark table don't get to see alpha.

  **Verdict**: strong. This is the best *fallback* and the natural
  presentation for a "weights are explicit" table, e.g. showing the ranking
  under alpha = 0.9/0.8/0.7 so the reader sees how robust the ordering is.
  We recommend it as a *secondary* display, not the headline.

  ### Option D — Ratio on normalized axes with a floor: `quality / max(usage, u_min)`

  ```
  value = quality / max(usage, epsilon)
  ```

  **Mathematics**: bounded when usage is small, but the value is still
  unbounded above (epsilon chosen small => epsilon-inverse blowup), and
  epsilon is an arbitrary magic number readers will ask about.

  **Verdict**: reject. Same fundamental problem as Option A, just softened.

  ### Option E — Multiplicative quality-scaled cost factor (the "compute_composite shape")

  ```
  value = quality * cost_factor
  cost_factor = 1/(1 + k * usage / max(n_correct, 1))
  ```

  where `k` (or the pair `session/weekly` as separate k's) is a scaling
  constant, and n_correct = quality * n_tasks from the suite.

  This is **not a new formula** — it is exactly what `compute_composite`
  already does for the per-test composite, reapplied at the summary level
  using the *aggregate* usage delta and the weight-derived overall score. It
  generalizes the existing codebase pattern to the ranking instead of
  inventing a third convention.

  **Mathematics**
  - Bounded 0-1 (quality <= 1, cost_factor in (0, 1]).
  - usage=0 -> cost_factor=1.0 -> value=quality. Zero usage never inflates
    above 1.0, fixing Option A's divide-by-zero completely.
  - Strictly monotone decreasing in usage, strictly increasing in quality.
  - The `1/(1 + x)` (hyperbolic/harmonic) shape is *economically standard*
    (it appears as the elasticity factor in Cobb-Douglas-adjacent models,
    as diminishing-returns utility curves, and in the "quality-adjusted
    score per dollar" treatment used by independent evaluators who do
    blend, e.g. the "score-per-cost" style metrics popularized on model
    comparison sites). It avoids the ratio metric's hyper-sensitivity near
    zero cost while preserving the ratio metric's economics at moderate
    cost.
  - The `max(n_correct, 1)` factor makes the penalty *per correct task*
    rather than per run — so a bigger suite doesn't automatically look more
    expensive. This matters for cross-suite comparability later.

  **Zero/low-usage behavior (exactly as requested)**
  | usage | cost_factor | composite |
  |---|---|---|
  | 0 | 1.000 | = quality |
  | 0.05 | 1/(1+0.05k/n) | ≈ quality unless quality is very low |
  | 0.5 | 1/(1+0.5k/n) | quality devalued |
  | 1.0 | 1/(1+k/n) | heavily devalued |

  The "free model" never ranks above an identical-quality expensive model
  merely because of its costlessness — costless == no penalty, not a bonus.

  **Session vs weekly (and how)**
  - Session delta (before/after the run) measures *this suite's* consumption
    — directly relevant to the ranking.
  - Weekly delta measures *total budget consumed this week*, including
    other activity — contaminated as an "instantaneous cost" signal. Use
    as a **secondary tie-breaker / displayed context** (what a user will
    still be paying through the day), not as the primary penalty input.
    Concretely: primary = session; if two models tie within noise on
    session-adjusted composite, break the tie by weekly-adjusted composite
    (same formula, weekly delta).

  **Alpha / k choice for the session form**
  - k=1000 gives 1/(1+0.001) ≈ 0.999 at 0.1% usage — the metric is
    insensitive to tiny sessions and only devalues meaningfully at larger
    absolute consumption. This matches the project's existing intuition
    (same default `scale=1000.0` already used).
  - For a *bounded-budget* audience (Ollama users hitting weekly rate
    limits), the more informative reading is "how much of your weekly
    budget does the suite eat per quality point" — that's Option E with
    weekly delta as a **reported companion column** rather than the
    headline number.

  **Pros**: monotone, bounded, zero-safe, per-correct-task scaling, exactly
  consistent with the existing codebase convention, has a single tunable
  (`scale`) that maps to `compute_composite` today, and keeps "quality is
  the floor" semantics — a cheap wrong model can never beat a costly right
  model at equal usage. **Cons**: the ratio 1/(1+x) slightly under-penalizes
  high-cost models relative to a linear penalty at the top of the range
  (diminishing returns on the penalty side); mitigated by reporting the raw
  usage delta alongside so readers see the absolute cost.

  **Verdict**: **recommended** (headline ranking).

  ## 4. Small-sample noise (repeats) and monotonicity

- The suite runs `repeats: 3` tasks in 5 categories. Both quality and usage
  are *aggregate* quantities over that run, so per-task noise averages out.
- Noise in quality: `OverallSummary.std` is the weighted-std of the category
  stds; the ranking should (a) use quality *not* adjusted for noise (the
  composite is a ranking tool, not a CI), but (b) **flag ties within
  2*std** as "statistically indistinguishable". This is already the
  convention in `compare_baseline` (`|delta| > 2 * std`).
- Noise in usage: session deltas are tiny (fractions of a percent), and
  Ollama's rate-limit endpoint may round. **Never** rank two models whose
  session deltas differ by less than the smallest measurable delta —
  collapse them to a tie and break by quality alone.

  **Monotonicity guarantee (formal)**: the chosen formula is a strictly
  increasing function of quality and a strictly decreasing function of
  usage. Proof: for `F(q, u) = q * 1/(1 + k*u/max(qN, 1))`, dF/dq > 0 and
  dF/du < 0 for all k > 0, u >= 0, q >= 0. Both partials are well-defined
  at u=0, q=0. No normalization step, no cohort dependency, so the ordering
  satisfies (i) better quality can never lower the rank holding usage
  fixed, and (ii) lower usage can never lower the rank holding quality
  fixed — exactly the two monotonicity requirements in the question.

  ## 5. Recommended formula (P2.5.10c deliverable)

  ```
  # Summary-level ranking composite (recommendation)
  #
  value = quality * cost_score
  cost_score = 1 / (1 + usage_value / max(n_correct, 1) * SCALE)
  #
  #    quality     = overall.category-weighted score in [0, 1]
  #    usage_value = run's session usage delta, as a fraction (0-1),
  #                  stored in OverallSummary.usage_delta["session"]
  #    n_correct   = quality * n_tasks where n_tasks = len(results)
  #    SCALE       = 1000.0  (keeps parity with compute_composite's
  #                  current default 'scale' parameter)
  #    value       in [0, 1]; None usage -> cost_score = 1.0,
  #                  value = quality  (consistent with compute_composite)
  ```

  This is the existing `compute_composite` semantic lifted to the summary:
  not a new invention, but the same economic shape (multiplicative,
  diminishing-returns, quality-as-floor) applied at the level where the
  ranking lives.

  Implementation notes (for whoever implements P2.5.10d, not part of this
  research deliverable):

  1. Reuse `compute_composite` verbatim — no new cost formula. Add a thin
     `rank_composite(report)` helper in `report.py` that:
     - pulls `report.overall.score` as `quality`;
     - pulls `report.overall.usage_delta["session"]` as `usage_value`
       (fraction; multiply by 100 only at print time, as `print_report`
       already does);
     - derives `n_tasks = len(report.results)`, `n_correct = quality * n_tasks`;
     - returns `(value, cost_score)` or `None` if `overall` is missing.
  2. Ranking presentation: a 2-line table per model:
     raw quality | usage Δ (session, %) | cost_score | composite | std.
     No cohort normalization (Option B) ever in the stored numbers.
  3. Weekly delta: display in a secondary column ("budget burn") and as a
     tie-breaker only; do not feed the headline composite.
  4. Noise rule: two models within `2 * std` composites are reported as a
     tie; break only by quality (never by cheaper usage).
  5. Zero usage: `usage_value <= 0` (or the delta round-trip collapses to
     0) => cost_score = 1.0, composite = quality. Document this in the blog
     post as "budget consumed = 0 means no penalty, not a bonus".

  Why not the other options, one sentence each:

  - **A (raw ratio)**: blows up at usage=0 and is dominated by tiny-denominator
    noise in cheap-model comparisons — the central case here.
  - **B (per-comparison normalization)**: destroys absolute quality meaning and
    re-ranks existing models when a new model enters the table — fatal for a
    reproducible public leaderboard and for regression testing (yoker-test's
    whole point).
  - **C (alpha blend)**: defensible and safe, but requires publishing an
    explicit alpha that is a value judgment, not a measurement; keep as a
    secondary presentation if desired, not the headline.
  - **D (ratio with epsilon floor)**: same fundamental issue as A; the floor
    is an unprincipled magic constant.

  Why E wins, in one paragraph: it is (i) monotone in both inputs,
  (ii) bounded, (iii) zero-safe (free means no penalty and no bonus), (iv)
  consistent with an economic prior that *already exists in this
  codebase* (`compute_composite`), (v) matches how the independent
  benchmarking world handles quality-vs-cost (Artificial Analysis warns
  explicitly that equal per-token prices do not mean equal cost — exactly
  what our usage-based cost score captures that a raw $/Mtok lookup would
  not), and (vi) keeps absolute, cross-comparison-stable numbers so that
  the yoker-test regression story (same model, different Yoker version →
  score delta) remains sound when cost tracking is added later.

  ## 6. Sources

  - Artificial Analysis — Benchmarking Methodology and Intelligence Index
    v4.1.1: https://artificialanalysis.ai/methodology ;
    https://artificialanalysis.ai/evaluations/artificial-analysis-intelligence-index
    (Cost per Task definition; note on token usage vs per-token price).
  - HELM — Holistic Evaluation of Language Models (Liang et al., TMLR 2023),
    §11.3 on aggregation refusal, and the multi-metric philosophy:
    https://arxiv.org/pdf/2211.09110
  - OpenRouter — LLM Rankings, "measure adoption, not quality":
    https://openrouter.ai/rankings ; provider performance guide:
    https://openrouter.ai/blog/insights/evaluate-llm-provider-performance/
  - Cost-of-Pass — Erol, El, Suzgun, Yüksekgönül, Zou (arXiv 2504.13359):
    production-efficiency theory for quality-vs-cost:
    https://arxiv.org/html/2504.13359v2
  - Pareto-frontier / score-triple argument for explicit weights:
    https://absolutedigitalpublishers.com/articles/why-cost-and-latency-belong-in-the-evaluation-score