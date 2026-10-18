# AI Use: HW6

1. **What I used an AI assistant for, and what I did myself:**

I used Claude to write first drafts of most of the code: the MongoDB schema validator and the FastAPI document routes with Pydantic validation, the memory service (short-term window, summaries, episodic facts, `/api/chat`, `/api/memory`, `/api/aggregate`), the Part 3 experiment script and probes file, the file-memory module (`AGENT.md`/`MEMORY.md` loading, consolidation checks, `/memory`, `/compact`, `/dream`, `/help`), the AGENT.md compliance checker, the 55-line test `MEMORY.md`, and `verify_hw06.py`. It also drafted my analysis text and the MongoDB-versus-file comparison. I installed and ran everything on my own machine (MongoDB, Ollama, the API), tested the endpoints in Swagger and Compass, ran every experiment and test, took the screenshots, committed the original and consolidated `MEMORY.md` as separate commits, read the results, and decided what to keep.

2. **One AI-produced output that was wrong or unsuitable:**

The generated code for the Part 3 sweep ran the model with qwen3's thinking mode on, and it did not account for it. The model produced hidden reasoning before every answer, and those tokens were billed as output tokens. The result looked plausible but was inflated: roughly 350 output tokens per turn instead of about 60, and about 23 seconds per turn instead of 4 to 7, so a 10,000-conversation cost estimate came out about 3.5 times too high. The AI's first fix, adding a `/no_think` hint to the prompt, did not stop it.

3. **How I detected the problem or verified the result:**

I looked at the per-turn numbers in `token_log.csv` instead of trusting the summary. The completion tokens per turn were far larger than the short replies I could see, and latency was around 23 seconds. I compared that with the reply lengths in the transcript. For the consolidation test, I read `consolidation_log.md` line by line against the original file, and I checked the pet-policy lines in `MEMORY_consolidated.md` by hand.

4. **What I changed and why it works now:**

I set `reasoning=False` when creating the Ollama client, which actually turns thinking off, and re-ran the full sweep. Output tokens dropped to match the visible replies and latency fell to 3.6 to 7.1 seconds per turn. I kept the old thinking-on results in `raw_thinking_on/` and `METRICS_thinking_on.md` as an ablation, so the cost of thinking mode is documented rather than hidden. For consolidation, I did not edit the output to look better. I kept the real result, reported the wrongly resolved contradiction in the report, and noted that a rule-based "newest date wins" step is only as good as the contradiction pairs the model finds.