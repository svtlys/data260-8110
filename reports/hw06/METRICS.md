# METRICS - HW6 Part 3 (SID4 8110, SEED 8110)

Model: qwen3:8b via Ollama, temperature 0, thinking disabled (`/no_think`). SHORT_TERM_N counts messages (user + assistant). 30 scripted user messages, then 5 probes (`memory_probes.yaml`). Token counts are Ollama's real prompt/completion counts; per-component counts split the real prompt count in proportion to characters.

## Table 1 - SHORT_TERM_N sweep (policy = full: window + summaries + episodic facts)

| SHORT_TERM_N | mean prompt tokens | mean completion tokens | mean latency (ms) | mean probe score (1-5) |
|---|---|---|---|---|
| 4 | 407.2 | 39.8 | 3584 | 5 |
| 12 | 605.2 | 43.8 | 5224 | 5 |
| 30 | 956.1 | 41.6 | 7132 | 5 |

## Table 2 - eviction / compression policy comparison

fifo = sliding window only (old messages evicted and lost); summary = evicted messages are compressed into session + lifetime summaries; full = summaries + episodic facts retrieved by cosine.

| policy | N | mean prompt tokens | mean latency (ms) | mean probe score | maintenance calls | maintenance tokens (in/out) |
|---|---|---|---|---|---|---|
| fifo | 4 | 197.5 | 3398 | 1 | 0 | 0/0 |
| full | 4 | 407.2 | 3584 | 5 | 10 | 3735/1171 |
| summary | 4 | 375.8 | 4701 | 4.6 | 10 | 3672/1048 |
| fifo | 12 | 380.9 | 4071 | 1 | 0 | 0/0 |
| full | 12 | 605.2 | 5224 | 5 | 10 | 3646/1001 |
| fifo | 30 | 694.8 | 5974 | 1 | 0 | 0/0 |
| full | 30 | 956.1 | 7132 | 5 | 10 | 3781/1143 |

## Table 3 - mean prompt tokens by component (per chat turn)

| run | primer | long-term summary | episodic facts | short-term window | user msg |
|---|---|---|---|---|---|
| fifo_N4 | 61.5 | 0.0 | 0.0 | 124.5 | 11.5 |
| full_N4 | 57.2 | 205.3 | 19.3 | 114.9 | 10.7 |
| summary_N4 | 56.6 | 190.1 | 0.0 | 118.9 | 10.6 |
| fifo_N12 | 60.3 | 0.0 | 0.0 | 309.4 | 11.1 |
| full_N12 | 57.8 | 180.4 | 19.6 | 336.6 | 10.8 |
| fifo_N30 | 60.4 | 0.0 | 0.0 | 623.1 | 11.1 |
| full_N30 | 59.2 | 207.8 | 20.1 | 657.9 | 11.0 |

## Table 4 - cost of 10,000 30-turn conversations at $1.0/M input, $5.0/M output

Tokens per conversation include chat turns plus summarisation calls (probes excluded). This is a hypothetical price; the local model costs nothing.

| run | input tokens / conv | output tokens / conv | cost for 10,000 convs | probe score |
|---|---|---|---|---|
| fifo_N4 | 5924 | 1232 | $120.84 | 1 |
| fifo_N12 | 11427 | 1126 | $170.57 | 1 |
| fifo_N30 (worst quality) | 20843 | 1136 | $265.23 | 1 |
| summary_N4 | 14947 | 2321 | $265.52 | 4.6 |
| full_N4 (best quality) | 15951 | 2365 | $277.76 | 5 |
| full_N12 | 21802 | 2316 | $333.82 | 5 |
| full_N30 | 32463 | 2391 | $444.18 | 5 |

## Analysis

Window size (Table 1): With all memory tiers on, increasing SHORT_TERM_N from 4 to 12 to 30 raised mean prompt tokens from 407 to 605 to 956 and mean latency from 3.6 s to 5.2 s to 7.1 s, while the mean probe score stayed at 5.0 in all three runs. A bigger window therefore bought no recall, because the five probed facts (told in messages 1–6) were recovered from the episodic store and summaries, not from the window.

Eviction policy (Table 2): At N=4, plain FIFO eviction scored 1.0 on every probe: the facts were gone by message 30, and the model correctly said it didn’t know. FIFO at N=30 also scored 1.0, since 30 messages cover only the last 15 turns. Summarize-then-evict scored 4.6, and adding episodic fact retrieval scored 5.0. The one probe the summary-only run lost points on was P5, where it kept “no carpet” but dropped the reason (the cats); the retrieved raw fact preserved it. Table 3 shows why episodic memory is efficient: it cost only about 20 prompt tokens per turn, versus about 200 for the long-term summaries.

Cost of the policy (Tables 3–4): Maintenance (10 summarization calls per conversation) used about 3.7k input and 1.1k output tokens, roughly a third of the full_N4 cost. Even so, full_N4 at $277.76 per 10,000 conversations is the cheapest setting with perfect recall.

Caveats: Each setting was run once at temperature 0, so there is no variance estimate. Component token counts are apportioned from the real prompt count by character share. The latency increase at N=30 is probably partly caused by Ollama’s prompt-cache reuse breaking once the window starts sliding (the prefix changes every turn). I haven’t verified that explanation.
