# AI_USE.md - HW10 (dashboard, evaluator with judge validation, tracing)
## 1. What I used an AI assistant for, and what I did myself

I used Claude to design and write the code: the span tracing added to my HW8 pipeline and HW9 cache (`tracing.py`, `traced_service.py`, changes to
`agent_core.py`, `semantic_cache.py`, `agent_adapter.py`), the evaluator and DeepEval judge wrapper (`pipeline_eval.py`, `judge.py`), the judge validation scripts, the 50-request latency experiment, `verify_hw10.py`, and  `make_metrics_hw10.py`

I did the following myself: started Docker, Kafka, MySQL, Ollama and the Planner, Writer and Reviewer agents; installed the dependencies; exported my own database password in each terminal (it is not in any file); ran every script, test and experiment; **read the 20 Writer drafts and gave each a 1-5 label by hand before any judge score existed, and committed the cases and labels first**; took the screenshots; reported errors; decided what goes in the report; and kept the Part 3 result as it came out (the judge disagreed with me) instead of tuning it. Claude could not run Kafka, Ollama, MySQL, DeepEval or Streamlit in its own environment, so none of that code was tested against the real services until I ran it. The offline tests use fake judges and an in-memory broker.

## 2. One AI output that was wrong/unsuitable, and one thing I independently verified

**Wrong/unsuitable:** several of the instructions I was given did not work on my machine as written. I exported placeholder passwords that I had copied literally,
which gave MySQL `Access denied`; one pasted comment containing an apostrophe left my shell stuck at `quote>`; my Mac went to sleep during the evaluation run and broke the Kafka
sessions, so I had to restart the agents and use `caffeinate`; and the first dashboard theme was unreadable in dark mode (white text on white cards, black chart backgrounds),
so it was changed to a white-card, light-blue layout.

**Independently verified:** I did not accept the judge's scores. I labeled the drafts myself and compared: Spearman -0.14, mean absolute difference 1.1, and the judge gave 5.0 to
3 of the 4 drafts I labeled 1-2 (including one with an invented rent figure). For the latency table I checked that all 50 requests were cache misses according to their own
`cache_lookup` span, and `verify_hw10.py` recomputes the end-to-end p50 and the judge statistics from the saved CSV files.

## 3. How I detected the problem / verified the result

- Wrong passwords showed as `Access denied ... (using password: YES)`; I checked the length of the variable with `echo ${#MYSQL_ROOT_PASSWORD}`.
- The sleep problem showed as Kafka session-timeout lines in the agent terminals; after restarting the agents and running under `caffeinate` the evaluation saved all 5 results.
- The unreadable dashboard was visible in my screenshot of the Summary page.
- Evaluation results: all 5 end-to-end questions scored 5.0 except one plan (4.2), and the final answer was identical to the draft in every case, so I report that the Reviewer
  added no improvement instead of claiming one.
- Latency: Evaluation was 69.1% of cache-miss end-to-end time, Writer 18.5%, Planner 11.4%; I report evaluation as the dominant contributor.

## 4. What I changed and why it works now

- I typed my real password myself with `read -s` in each terminal, kept the agents running and the Mac awake for long runs, and ran scripts from `code/`.
- The dashboard now uses white tables and charts on a light-blue page, so it reads the same whatever theme the browser uses.
- Limits I am aware of: the judge (an 8B local model) is not reliable enough to gate anything (see Part 3); 20 labeled drafts and one labeler are too few to give narrow confidence; the Part 2 run used 5 questions; the Reviewer only forwards the draft, so "no improvement" is a property of my pipeline and not a verdict on the evaluator; and the end-to-end latency includes the (slow) evaluation step, which does not have to be on the user's critical path.