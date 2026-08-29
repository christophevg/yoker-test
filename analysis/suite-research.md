> **Recovery note**: Research report recovered verbatim from a lost session's log (`researcher-frameworks.txt`). Research for task P2.5.4 (LLM evaluation frameworks for the improved suite) was completed in that session; this document preserves the full sourced report.

                                     LLM Benchmarking Frameworks: A Survey
1. Major Benchmark Datasets
1.1 MMLU (Massive Multitask Language Understanding)
MMLU (Hendrycks et al., 2021) is a 57-subject academic knowledge benchmark of 14,042 multiple-choice questions
spanning elementary to expert level.
Scoring Method:

 • Metric: 5-shot accuracy (5-shot CoT prompting by default)
 • Format: 4-choice multiple choice (A-D)
 • Protocol: Models are given 5 example questions and answers from the same subject before answering the test
   question
 • Scoring approaches:
    • Log-probability ranking: Present question, score log-probability for each continuation (letter A-D), pick
      highest
    • Generate and parse: Ask model to answer, let it emit text, extract letter with regex
 • Ceiling: High (frontier models 86-89%, approaching ~89.8% expert human average)
 • Known issues: Label errors, performance saturation, prompt sensitivity (4-5%)
MMLU-Pro (Wang et al., NeurIPS 2024) addresses MMLU's limitations:

 • 12,032 questions across 14 disciplines
 • 10 answer choices (vs. 4) → reduces guessing floor from 25% to 10%
 • 3× more distractors
 • Expert-reviewed to remove trivial/noisy questions
 • Scoring: 5-shot Chain-of-Thought (CoT) → extracts answer via regex patterns
 • Key results: GPT-4o achieves 72.6% (vs. 87.4% on MMLU)
 • Prompt robustness: Sensitivity decreased from 4-5% to ~2% with 10 options
1.2 HumanEval (Code Generation)
HumanEval (Chen et al., 2021) contains 164 hand-written Python function-completion problems.
Scoring Method:

 • Metric: pass@k (pass@1, pass@10, pass@100)
 • Format: Model generates function completion; evaluated by executing unit tests
 • Protocol: Generate n samples, measure fraction that pass all tests
 • pass@1: Single greedy sample, check if tests pass
 • pass@k: Generate k samples, check if at least one passes (unbiased estimator)
 • Saturation: High (models routinely exceed 90% pass@1)
 • Security note: Evaluating untrusted code requires sandboxed execution
1.3 GSM8K (Grade School Math)
GSM8K (Cobbe et al., 2021) contains 8,500 grade-school math word problems requiring 2-8 steps of basic
arithmetic.
Scoring Method:

 • Metric: Exact match of final numeric answer
 • Format: Extract number after "####" marker, compare to gold answer
 • Protocol: Few-shot CoT prompting, extract last numeric answer from response
 • Saturation: High (top models achieve 95%+)
 • Known issue: Data contamination concerns (GSM1k study showed up to 8% performance drops on fresh problems)
1.4 SWE-bench (Software Engineering)
SWE-bench (Jimenez et al., ICLR 2024) contains 2,294+ real GitHub issues from major Python projects (Django,
matplotlib, astropy, etc.).
Scoring Method:

 • Metric: Percentage of issues resolved (test pass rate)
 • Format: Given a codebase and an issue description, model generates a patch
 • Protocol: Generate patch, apply to repo, run test suite (FAIL_TO_PASS + PASS_TO_PASS tests)
 • Evaluation: Docker containerized, automated test execution
 • Saturation: Low (Claude 4.5 Opus 2026: 76.8% on Verified; significant room for improvement)
 • Subsets:
    • SWE-bench Verified: 500 human-validated instances
    • SWE-bench Lite: subset for faster evaluation
 • Key metric: % resolved — percentage of instances where all FAIL_TO_PASS tests pass without breaking
   PASS_TO_PASS tests
1.5 GPQA (Graduate-Level Science)
GPQA (Rein et al., 2023) contains 448 expert-crafted questions in biology, physics, and chemistry.
Scoring Method:

 • Metric: Multiple-choice accuracy (4-way, shuffled)
 • Difficulty: PhD experts achieve 65%, non-experts 34% with web access
 • Scoring: Same log-probability or generation+extraction as MMLU
 • Saturation: Medium (key component of Open LLM Leaderboard v2)
1.6 TruthfulQA
TruthfulQA (Lin et al., 2021) contains 817 questions targeting common human misconceptions across law,
medicine, finance, and politics.
Scoring Method:

 • Metric: Fraction of truthful answers
 • Format: Open-ended generation, scored by separate judge model
 • Saturation: Medium-high
 • Known issue: Inverse scaling originally observed (larger models were less truthful)
1.7 MATH (Competition Math)
MATH (Hendrycks et al., 2021) contains 12,500 competition-level math problems across 7 subjects at 5 difficulty
levels.
Scoring Method:

 • Metric: Exact match of final boxed answer
 • Format: Solutions have boxed answers; extract answer, normalize, compare
 • Protocol: 4-shot CoT prompting
 • Saturation: Medium (Level 5 problems remain discriminative)
 • Progress: From 7% (2021) to 90%+ (2025)
---------------------------------------------------------------------------------------------------------------
2. Holistic Evaluation Frameworks
2.1 HELM (Holistic Evaluation of Language Models)
HELM (Liang et al., Stanford CRFM) is a multi-metric, multi-scenario evaluation framework.
Core Design Principles:

 1 Broad coverage with recognition of incompleteness — taxonomize scenario/metric space, explicitly state
   what's missing
 2 Multi-metric measurement — measure 7 metrics per scenario:
    • Accuracy (exact match, F1, ROUGE)
    • Calibration (ECE — Expected Calibration Error, 10-bin)
    • Robustness (worst-case accuracy under perturbations: typos, contractions, etc.)
    • Fairness (counterfactual fairness: dialect, gender, race perturbations)
    • Bias (demographic representation in generations)
    • Toxicity (PerspectiveAPI score of generations)
    • Efficiency (denoised/idealized inference runtime)
Scoring Method:

 • 16 core scenarios × 7 metrics = 98 of 112 possible (scenario, metric) pairs measured
 • Multiple-choice adaptation methods:
    • Joint: All choices concatenated, model predicts letter
    • Separate: Each choice scored independently
    • Separate-calibrated: Separate + calibration by answer-only probability
 • Adaptation: 5-shot prompting with standardized prompts
 • Aggregation: Head-to-head win rates across all scenarios and metrics
Key Findings:

 • Instruction tuning highly effective (text-davinci-002 wins 90%+ of comparisons)
 • Accuracy correlates strongly with robustness and fairness
 • Calibration is scenario-dependent
 • Scale > 50B parameters needed for consistently above-chance win rate
2.2 EleutherAI LM Evaluation Harness
LM-Eval-Harness (Gao et al., EleutherAI) is the backend for Hugging Face's Open LLM Leaderboard.
Architecture:

 • 60+ standard academic benchmarks implemented
 • YAML-based task configuration:

   task: mmlu_subject
   dataset_path: cais/mmlu
   output_type: multiple_choice  # or generate_until, loglikelihood
   doc_to_text: "{{question}}\nA. {{choices[0]}}..."
   doc_to_choice: ["A", "B", "C", "D"]
   doc_to_target: answer
   metric_list:
     - metric: acc
     - metric: acc_norm  # length-normalized

 • Output types:
    • generate_until: Free-form generation (greedy or sampled)
    • loglikelihood: Score continuation probability
    • loglikelihood_rolling: Perplexity evaluation
    • multiple_choice: Score each choice, pick highest
Scoring Methods by task type:

 • Multiple choice: Compare log-probabilities of each answer choice, select argmax
 • Generate_until: Generate text until stop sequence, extract answer, compare
 • Metrics: acc, acc_norm, exact_match, f1, bleu, perplexity, mcc (Matthews correlation)
Key features:

 • Model backends: HuggingFace, vLLM, OpenAI API, Anthropic, local servers
 • Caching for reproducibility
 • Bootstrap confidence intervals (100k iterations default)
 • Filters for post-processing (regex extraction, majority voting)
2.3 OpenAI Simple-Evals
Simple-Evals (OpenAI) is a lightweight evaluation framework.
Built-in benchmarks:

 Benchmark           Scoring                       Type
 ────────────────────────────────────────────────────────────────────────
 MMLU                multichoice_regex             4-way MCQ
 MMLU-Pro            multichoice_regex             10-way MCQ
 MATH-500            answer_line                   Math
 GPQA Diamond        multichoice_regex (shuffled)  MCQ
 GSM8K               numeric_match                 Math reasoning
 DROP                fuzzy_match                   Reading comprehension
 HumanEval           code_sandbox                  Code generation
 SimpleQA            needs_judge                   Factuality (LLM judge)
 SWE-bench Verified  swebench_score                Software engineering

Scoring approaches:

 • multichoice_regex: Extract letter from "Answer: X" pattern
 • numeric_match: Extract last number from response
 • code_sandbox: Execute code in Docker, run tests
 • needs_judge: LLM judge evaluates answer correctness
---------------------------------------------------------------------------------------------------------------
3. Instruction Following & Chat Evaluation
3.1 MT-Bench (Multi-Turn Benchmark)
MT-Bench (Zheng et al., NeurIPS 2023) contains 80 multi-turn questions across 8 categories.
Scoring Method:

 • Metric: 1-10 scale score by GPT-4 judge
 • Format: Two-turn conversations; model maintains context across turns
 • Protocol: GPT-4 scores each turn independently, then aggregates
 • Evaluation modes:
    • Single-answer grading: GPT-4 scores response 1-10
    • Pairwise comparison: GPT-4 compares two responses head-to-head
 • Aggregation: Average score across turns and questions
 • Saturation: Medium-high (GPT-4 scores ~9.0/10)
3.2 AlpacaEval
AlpacaEval (Li et al., Stanford) is an automatic evaluator for instruction-following.
Scoring Method:

 • Metric: Win rate against reference model (GPT-4 Turbo)
 • Format: 805 open-ended instructions
 • Protocol: GPT-4 judge compares model output vs. reference output
 • AlpacaEval 2.0: Uses GPT-4 Turbo as both annotator and baseline
 • Length-controlled (LC) win rates: Debias against length preference
    • Fit GLM to predict: preference = f(model_identity, length_difference, instruction_difficulty)
    • Counterfactual: "What would preference be if model output had same length as baseline?"
    • LC increases correlation with Chatbot Arena from 0.94 to 0.98 Spearman
Key properties:

 • win_rate(m, b) = 100% - win_rate(b, m) ∈ [0, 100%]
 • win_rate(m, m) = 50%
 • Cost: <$10, <5 minutes
 • Correlation with Chatbot Arena: 0.98 (Spearman)
3.3 Chatbot Arena (LMSYS)
Chatbot Arena (Chiang et al., NeurIPS 2024) is a live human evaluation platform.
Scoring Method:

 • Metric: Elo rating (Bradley-Terry model)
 • Format: Users chat with two anonymized models side-by-side, vote for better one
 • Protocol: Pairwise comparisons converted to Elo ratings
 • Aggregation: Bradley-Terry model → Elo scores
 • Key properties:
    • Dynamic, hard to saturate
    • Real user interactions
    • Largest publicly available human evaluation
    • Differences in Elo convert to win rates
Correlation with automatic benchmarks:

 • AlpacaEval-LC: 0.98 Spearman
 • MT-Bench: 0.94
 • MMLU-Pro: 0.85
---------------------------------------------------------------------------------------------------------------
4. Meta-Evaluation: Evaluating the Evaluators
4.1 REIFE (Re-evaluating Instruction-Following Evaluation)
REIFE (Liu et al., NAACL 2025) is a large-scale meta-evaluation of LLM-based evaluators.
Key Findings:

 • 25 base LLMs × 15 evaluation protocols = 375 LLM-evaluators
 • Base LLM performance ranking remains consistent across protocols (Spearman 0.98)
 • Evaluation protocol effectiveness depends on base LLM capability
 • Best open-source evaluator: Llama-3.1-405B (84.5% avg accuracy)
 • Best protocol: PrePAIR (pointwise reasoning enhanced pairwise)
 • Different datasets exhibit varying difficulty; need multiple datasets for robust evaluation
4.2 LLM-as-a-Judge Biases
Known biases:

 1 Position bias: Prefer first output presented (mitigated by randomization)
 2 Length bias: Prefer longer outputs (~68% probability; LC controls this)
 3 Self-bias: Prefer own outputs (GPT-4 prefers GPT-4 82.5% of time)
 4 Format bias: Prefer outputs with lists, bold, structured formatting
 5 Self-consistency: Low agreement when re-evaluated (variance ~15-20%)
---------------------------------------------------------------------------------------------------------------
5. Summary Comparison Table

 Benchmark      Domain          # Questions   Metric          Saturation  Judge
 ───────────────────────────────────────────────────────────────────────────────────────
 MMLU           57 subjects     14,042        5-shot acc      89%         Rule-based
 MMLU-Pro       14 disciplines  12,032        5-shot CoT acc  73%         Rule-based
 HumanEval      Code            164           pass@k          90%+        Test execution
 GSM8K          Math            8,500         Exact match     95%+        Rule-based
 SWE-bench      SE              2,294         % resolved      77%         Test execution
 GPQA           Science         448           MCQ acc         65% expert  Rule-based
 MT-Bench       Chat            80            1-10 score      9.0/10      GPT-4 judge
 AlpacaEval     Instructions    805           Win rate        -           GPT-4 judge
 Chatbot Arena  Chat            Live          Elo             -           Human
 HELM           Multi           42 scenarios  7 metrics       -           Mixed

6. Best Practices
 1 Never rely on a single benchmark — use multiple benchmarks covering different capabilities
 2 Report uncertainty — bootstrap confidence intervals, standard errors
 3 Control for prompt sensitivity — test multiple prompt formats
 4 Use standardized evaluation frameworks — HELM, LM-Eval-Harness for reproducibility
 5 Validate LLM judges — check agreement with human annotations (target >80%)
 6 Control for contamination — use held-out test sets, monitor for memorization
 7 Report raw scores, not just rankings — absolute performance matters for deployment decisions