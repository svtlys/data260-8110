# HW4 Part 4 — RAG Results and Analysis 

Draft ratings based on one run of rag.py (qwen3:8b, temperature 0.0, chunk_size=500, chunk_overlap=50, 492 chunks over 5 documents). Verify each rating against the printed chunks before submitting.

## Summary table

| Config | Accuracy (Q1-Q3 fully correct) | Faithfulness (no unsupported claims, Q1-Q6) | Format compliance (citations + exact refusal sentence) | Robustness (Q5/Q6 refused) |
|---|---|---|---|---|
| A: No RAG | 0/3 (Q3 partial) | n/a (no context) | n/a | 0/2 |
| B: Basic RAG | 3/3 | 4/6 (Q4 outside examples, Q6 answered from memory) | n/a (no citation rules; exact refusal sentence not used on Q5) | 1/2 (Q5 declined in own words, Q6 answered) |
| C: Context-engineered | 2/3 (Q2 partial) | 6/6 | 6/6 | 2/2, plus 1 false refusal (Q4) |

## top_k sweep (Q1, config C)

| k | Sources retrieved | Input tokens | Correct answer | Notes |
|---|---|---|---|---|
| 1 | sanjose_tpo (chunk 485) | 623 | yes | Only the relevant chunk |
| 3 | + sanjose_tpo (490, mobilehome rules), sanjose_resources | 1,495 | yes | Ranks 2-3 are distractors |
| 5 | + sanjose_tpo (491), ca_tenants_guide (64) | 2,141 | yes | Ranks 2-5 all distractors |

Best k for Q1: k=1 (same answer at about 30% of the tokens of k=5). Only Q1 was swept, so this says nothing about multi-chunk questions like Q2.

## Analysis (draft, roughly 430 words, edit into your own voice)

Retrieval worked well on Q1, Q2, and Q3. For Q1 the top result came from sanjose_tpo.txt and contained the 5% rule directly. Q2 needed two facts (the 120-day notice and the relocation table), and both showed up across the top-3 chunks, all from the same San Jose document. Q3 pulled chunks from two different documents, the CA tenants guide and the court self-help guide, which is what I wanted for the similar-information case. Q4 was the weak one: the query was short and vague, scores were only 0.55 to 0.60, only one of the three chunks was relevant, and the San Jose rent ordinance chunk never appeared. For Q5 and Q6 the top scores were low (0.36 and 0.10), which correctly signals that nothing relevant was in the corpus.

The biggest gap was between no RAG and RAG. Without context the model gave wrong answers on Q1 (7% instead of 5%) and Q2 (90 days and 150% of rent instead of 120 days and $10,353 plus $4,141), and it gave a confident mortgage rate on Q5 that came from no source. Basic RAG fixed the facts but not the behavior: on Q6 it still answered "Paris" from memory, and on Q4 it added San Francisco and New York examples that were not in the context.

The changes that helped most were the score filter and the grounding rules. Dropping chunks below 0.35 left Q6 with almost no context (98 input tokens versus 1,854 in Basic RAG) and cut Q5 from 1,769 to 619. Together with the exact refusal sentence, config C refused both Q5 and Q6 without hallucinating. Source labels and citations also made answers easier to check, especially on Q3, where the citations pointed to two documents.

Context engineering also had costs. On Q2, config C gave only the $10,353 base amount and dropped the $4,141 qualified assistance, so Basic RAG's fuller answer of $14,494 was better. On Q4, the strict refusal rule made config C refuse a question that had partial evidence, when a better answer would have said it depends on the city and building age. So grounding rules can cause over-refusal when retrieval is weak.

In the k sweep on Q1, k=1, 3, and 5 all gave the same correct answer, but input tokens rose from 623 to 1,495 to 2,141, and ranks 2 to 5 were mostly distractors such as a mobilehome chunk mentioning 7%. More context did not help here. I would use k=1 for a single-chunk question but keep k=3 as a default since Q2 needed several chunks; I only swept Q1, so this is a limited result.

Overall, answer quality depended on all three layers: retrieval had to find the right chunks, context filtering had to remove noise without dropping useful detail, and the prompt had to say when to refuse.