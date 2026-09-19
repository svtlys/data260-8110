
## Retrieval Quality Comparison (Part 2)

| Technique | Chunks | Avg chunk length | Top-1 cosine | Mean@k cosine | Mean retrieval latency |
|---|---|---|---|---|---|
| Token | 953 | 1156.0 chars | 0.691 | 0.667 | fast (sub-second per query) |
| Semantic | 302 | 3361.3 chars | 0.643 | 0.632 | fast (sub-second per query) |
| Sentence-window | 5935 | 171.0 chars | 0.709 | 0.667 | fast (sub-second per query) |

*(Note: exact per-query latency in ms is saved in reports/hw03/raw/chunking_comparison_results.csv. Latency numbers weren't printed to console per-technique summary but are recorded per retrieval call in the raw data.)*

## Confidently Wrong Retrieval Example

For Q1 ("maximum allowable rent increase under San Jose's Apartment Rent Ordinance"),
the **Semantic** technique's rank-3 result scored a high cosine similarity (0.659) but the chunk was actually about the *security deposit interest/itemized deduction fee* under California Civil Code § 1950.6, not about rent increase percentages at all. The embedding likely considered it similar because both this chunk and the correct answer discuss dollar figures, percentages, and "maximum allowable" language tied to landlord-tenant financial obligations, structurally and lexically similar phrasing, even though the actual subject (security deposit fees vs. rent increase caps) is different.
