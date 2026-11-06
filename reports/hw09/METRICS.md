# METRICS.md - HW9

Student: Alyssa Gomez | generated 2026-11-05T16:25:36 from reports/hw09/raw/ (not typed by hand)

## Section 0

SID4 8110 | PORT_BASE 8010 | PREFIX s8110 | SEED 8110 | VERIFY_SEED 268110 | DOMAIN_ID 6 (Rental Housing Listings)

Hardware: Apple M3, 16 GB RAM, macOS 26.6.2, Python 3.13.9

Model: qwen3:8b via Ollama (temperature 0 for Part 4); embeddings: all-MiniLM-L6-v2 (384-dim)

## Part 1 - Redis view counter

Key `s8110:views:listing:<id>`; INCR on every access; count written to the database every 10 increments (log line "Synced views to database").

## Part 2 - Semantic cache

Threshold 0.85. Queries: 12, hits: 6, **hit rate 50.0%**. Average latency: cached **30.29 ms**, not cached **9792.33 ms**.

| # | Kind | is_cached | similarity | latency (ms) |
|---|---|---|---|---|
| 1 | new | False | - | 24767.96 |
| 2 | new | False | 0.4962 | 7067.81 |
| 3 | new | False | 0.7138 | 5653.16 |
| 4 | new | False | 0.7367 | 6419.21 |
| 5 | exact duplicate | True | 1.0 | 43.73 |
| 6 | exact duplicate | True | 1.0 | 8.42 |
| 7 | paraphrase | False | 0.8489 | 5566.5 |
| 8 | paraphrase | True | 0.9459 | 52.24 |
| 9 | paraphrase | True | 0.9163 | 8.83 |
| 10 | new | False | 0.2617 | 9279.34 |
| 11 | exact duplicate | True | 1.0 | 60.17 |
| 12 | new | True | 0.9789 | 8.33 |

## Part 3 - Threshold sweep, cost model, stale answers

40 labeled cases. Costs: miss $0.01, hit $0.0001, false hit $5.0. Miss latency used: 9792.33 ms (measured in Part 2).

| Threshold | Hit rate | False-hit rate | Mean latency (ms) | Total cost | False-hit cases |
|---|---|---|---|---|---|
| 0.75 | 67.5% | 25.0% | 3198.9 | $50.1327 | c21, c22, c23, c24, c25, c26, c27, c28, c29, c30 |
| 0.8 | 65.0% | 25.0% | 3443.7 | $50.1426 | c21, c22, c23, c24, c25, c26, c27, c28, c29, c30 |
| 0.85 | 60.0% | 25.0% | 3933.4 | $50.1624 | c21, c22, c23, c24, c25, c26, c27, c28, c29, c30 |
| 0.9 | 57.5% | 25.0% | 4178.2 | $50.1723 | c21, c22, c23, c24, c25, c26, c27, c28, c29, c30 |
| 0.95 | 50.0% | 22.5% | 4912.6 | $45.202 | c21, c22, c23, c24, c25, c26, c27, c28, c29 |

**Chosen threshold: 0.95** (lowest total cost). Sensitivity: false-hit $0.5 -> 0.95, false-hit $5.0 -> 0.95, false-hit $50.0 -> 0.95, false-hit $500.0 -> 0.95.

### 3.5 Stale answer and invalidation

| Step | is_cached | stale_invalidated | Answer returned | Database says |
|---|---|---|---|---|
| 1 | False | False | The listing S8110-A01 has 3 available units. | S8110-A01 has 3 unit(s) available. |
| 2 | True | False | The listing S8110-A01 has 3 available units. | S8110-A01 has 0 unit(s) available. |
| 3 | False | True | The listing S8110-A01 has 0 available units. A listing with 0 availabl | S8110-A01 has 0 unit(s) available. |
| 4 | True | False | The listing S8110-A01 has 0 available units. A listing with 0 availabl | S8110-A01 has 0 unit(s) available. |

## Part 4 - Self-improving agents

### 4.2 Training

Training questions: 12; first-attempt failures: 2 (2 of them injected as a controlled test). Lessons created: 2.

### 4.3 Validation (validation_data.json, single attempt)

| Lesson | Pattern | Failures before | Failures after | Decision | Reason |
|---|---|---|---|---|---|
| lesson_001 | stale_price | 0 | 1 | REMOVE | failures 0->1; regressions ['va09']; unsupported answers [] |
| lesson_002 | controlled_risky_rule | 0 | 0 | KEEP | failures improved or unchanged, no regressions |

### 4.4 Variants on test_data.json

| Variant | Correct | Incorrect | Average attempts | Average latency (s) |
|---|---|---|---|---|
| Baseline | 18 | 2 | 1.0 | 1.59 |
| Evaluator Repair | 20 | 0 | 1.1 | 1.68 |
| Lesson Memory | 20 | 0 | 1.0 | 1.88 |
| Validated Improvement | 20 | 0 | 1.0 | 1.7 |

Incorrect test ids: Baseline: ['te14', 'te17']; Evaluator Repair: none; Lesson Memory: none; Validated Improvement: none
