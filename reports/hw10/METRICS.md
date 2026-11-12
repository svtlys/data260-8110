# METRICS.md - HW10

Student: Alyssa Gomez | SID4 8110 | PORT_BASE 8010 | PREFIX s8110 | SEED 8110 | VERIFY_SEED 268110 | DOMAIN_ID 6

Hardware: Apple M3, 16 GB RAM, macOS 26.6.2, Python 3.13.9
Local model: qwen3:8b through Ollama (agents and judge)

Every number below is read from the files in `reports/hw10/raw/`.

## Part 2 - evaluator results (end-to-end questions)

| # | Question | Plan quality | Writer helpfulness | Final helpfulness | Final minus draft | Evaluation time (s) |
|---|---|---|---|---|---|---|
| 1 | What should I check in the lease before signing a one-year rental agreement? | 5.0 | 5.0 | 5.0 | 0.0 | 24.288 |
| 2 | How can I tell whether a landlord is asking for an unreasonable security deposit? | 5.0 | 5.0 | 5.0 | 0.0 | 22.533 |
| 3 | How many units are available at listing S8110-A03? | 5.0 | 5.0 | 5.0 | 0.0 | 18.094 |
| 4 | What is the address of listing S8110-A05? | 5.0 | 5.0 | 5.0 | 0.0 | 19.654 |
| 5 | What can I do if the heater stops working and my landlord does not respond? | 4.2 | 5.0 | 5.0 | 0.0 | 22.825 |

## Part 3 - judge validation

Judge: deepeval GEval 4.3.4, model qwen3:8b, temperature 0.0, seed 8110, timeout 90.0 s.

| Metric | Value |
|---|---|
| Spearman rho (judge vs human, run 1) | -0.1355 |
| p-value | 0.569 |
| Mean absolute difference | 1.1 |
| Signed bias (judge - human) | 0.86 |
| Cases whose score changed across 3 runs | 0 / 20 |
| Mean / max absolute change | 0.0 / 0.0 |

| Case | Variant | Human | Judge run 1 | Run 2 | Run 3 |
|---|---|---|---|---|---|
| ec01 | general | 4 | 5.0 | 5.0 | 5.0 |
| ec02 | general | 5 | 4.2 | 4.2 | 4.2 |
| ec03 | general | 3 | 5.0 | 5.0 | 5.0 |
| ec04 | general | 5 | 5.0 | 5.0 | 5.0 |
| ec05 | general | 5 | 5.0 | 5.0 | 5.0 |
| ec06 | general | 5 | 5.0 | 5.0 | 5.0 |
| ec07 | general | 5 | 4.6 | 4.6 | 4.6 |
| ec08 | general | 4 | 5.0 | 5.0 | 5.0 |
| ec09 | with_database_facts | 4 | 5.0 | 5.0 | 5.0 |
| ec10 | with_database_facts | 4 | 4.6 | 4.6 | 4.6 |
| ec11 | with_database_facts | 5 | 5.0 | 5.0 | 5.0 |
| ec12 | with_database_facts | 2 | 5.0 | 5.0 | 5.0 |
| ec13 | with_database_facts | 5 | 5.0 | 5.0 | 5.0 |
| ec14 | no_facts_available | 1 | 5.0 | 5.0 | 5.0 |
| ec15 | no_facts_available | 4 | 5.0 | 5.0 | 5.0 |
| ec16 | no_facts_available | 5 | 4.6 | 4.6 | 4.6 |
| ec17 | off_topic_or_vague | 5 | 4.2 | 4.2 | 4.2 |
| ec18 | off_topic_or_vague | 5 | 5.0 | 5.0 | 5.0 |
| ec19 | mismatched_plan | 1 | 5.0 | 5.0 | 5.0 |
| ec20 | mismatched_plan | 1 | 3.0 | 3.0 | 3.0 |

## Part 4 - tracing and latency

50 requests, 50 confirmed cache misses by their cache_lookup span, 0 failed.

| Stage | p50 (ms) | p95 (ms) | % of cache-miss end-to-end | n |
|---|---|---|---|---|
| Cache lookup | 305.3 | 406.8 | 0.9 | 50 |
| Planner | 3856.8 | 5043.6 | 11.4 | 50 |
| Writer | 6284.3 | 7708.4 | 18.5 | 50 |
| Reviewer | 0.0 | 0.1 | 0.0 | 50 |
| Queue wait (total) | 27.2 | 40.5 | 0.1 | 50 |
| Evaluation | 24552.9 | 29509.8 | 69.1 | 50 |
| Unattributed (client, database lookup, cache write) | - | - | 0.0 | 50 |
| End-to-end (cache miss) | 35176.7 | 40836.2 | 100.0 | 50 |

Dominant contributor: **Evaluation** (69.1%). Cache-hit latency (separate metric): {'n': 10, 'p50_ms': 12.1, 'p95_ms': 160.1}.

### Required traces

| Example | trace_id | Path | Failing stage |
|---|---|---|---|
| cache_miss | ed335dd4-9b6c-4d46-9844-44483e3588be | cache_miss | - |
| cache_hit | ad060304-fc2e-4d84-ab93-652914f49f33 | cache_hit | - |
| failed | c7c6bafe-1f72-4922-9063-e217f13e0976 | cache_miss | planner |
