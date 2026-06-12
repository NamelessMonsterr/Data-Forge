# Quality Scoring Framework (Frozen)

> This is the heart of the system. The Planner, Quality Gate, Router (quality-based
> switching) and Certification all consume this spec. It is frozen BEFORE agent design.

## 1. Hard Gates (pass/fail, evaluated BEFORE any scoring)

A dataset that fails any hard gate is rejected regardless of its weighted score.
Every rejection is logged by the Auditor with a reason.

| Gate | Check |
|---|---|
| License | Compatible with the user's declared use (commercial / research / academic) |
| PII | No unresolved personally identifiable information after curation |
| Critical Toxicity | Toxicity ceiling not exceeded on sampled records |

```
Hard Gates -> PASS -> Weighted Quality Score
           -> FAIL -> Reject + Auditor entry (no score computed)
```

## 2. Weighted Metrics (0-100, computed only after gates pass)

| Metric | Type | Weight | Computation |
|---|---|---:|---|
| Completeness | Heuristic | 20 | required-field coverage, empty/missing ratio |
| Consistency | LLM Judge | 20 | sampled records judged for internal coherence |
| Diversity | Embedding | 15 | embedding dispersion / topic coverage |
| Duplicate Ratio | Heuristic | 15 | exact + near-dup (hash + shingle/minhash) |
| Formatting | Heuristic | 10 | schema conformity, encoding, parse errors |
| Readability | LLM Judge | 10 | sampled records judged for naturalness |
| Model Compatibility | Heuristic | 10 | token lengths, chat-template fit for target model |

`Quality = sum(metric_score * weight) / 100`

LLM-judged metrics are sampled (cost-bounded) and routed through the Hybrid Router.
Heuristic metrics are deterministic code - no API cost.

## 3. Quality Profiles (gate thresholds)

| Profile | Minimum Score |
|---|---:|
| Fast | 70 |
| Balanced | 80 |
| Production | 90 |
| Research | 95 |
| Enterprise | 98 |

Below threshold -> Planner starts a refinement cycle, subject to stopping conditions
(max iterations, budget, timeout, cancellation). The Auditor records the stop reason.

## 4. Certification mapping

| Certification | Requirement |
|---|---|
| Research Ready | score >= 95 and all hard gates pass |
| Production Ready | score >= 90 and all hard gates pass |
| Enterprise Ready | score >= 98, all hard gates pass, full audit trail |
