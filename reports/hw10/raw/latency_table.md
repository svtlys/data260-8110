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