
## N+1 Query Measurement (Part 3)

| Page size | Version | SQL stmts/req | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|
| 10 | naive | 11 | 4.2 | 5.0 | 6.5 |
| 10 | fixed | 1 | 1.9 | 2.0 | 2.9 |
| 50 | naive | 51 | 8.4 | 13.3 | 18.9 |
| 50 | fixed | 1 | 2.0 | 2.3 | 2.3 |
| 200 | naive | 201 | 29.3 | 30.1 | 30.6 |
| 200 | fixed | 1 | 3.7 | 4.3 | 12.6 |

## Speed-up Analysis

At page size 10, the fixed version is about 2.2x faster (4.2ms vs 1.9ms p50). At page size
50, that grows to about 4.2x faster (8.4ms vs 2.0ms). At page size 200, it's about 7.9x
faster (29.3ms vs 3.7ms).

The speed-up grows as page size increases because the naive version's query count scales
linearly with page size (page_size + 1 queries: 11, 51, 201), while the fixed version
always runs exactly 1 query no matter how many rows are on the page. Each extra query in
the naive version adds its own round-trip overhead (network latency to MySQL, query
parsing, connection handling) on top of actual data-fetching time -- so as page size grows,
the naive version's total latency grows roughly proportionally to the number of extra
queries, while the fixed version's latency barely grows at all (just a bit more data to
serialize per row, not more round-trips). This is exactly why N+1 is such a dangerous
pattern in production: it looks fine in testing with small pages, then degrades badly as
data or page size scales up.
