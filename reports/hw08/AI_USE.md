# AI_USE.md - HW8

## 1. What I used an AI assistant for, and what I did myself

I used Claude for debugging and consutling when it came to any questions I had with Docker and docker files. It also wrote the self-check script `verify_hw08.py`.

I did the following myself: set up Docker Desktop and Ollama on my MacBook Air, installed the dependencies, started every
container and agent, ran every command and experiment (`homework_demo.py`, the four-terminal pipeline run, and all four
`failure_tests.py` scenarios), took the screenshots, read the logs, fixed my own environment problems, and decided which results
go in the report. The AI could not run Kafka in its own environment, so none of its code was tested against a real broker until I ran it.

## 2. One AI output that was wrong/unsuitable, and one thing I independently verified

**Wrong/unsuitable:** the AI told me to install the requirements with `pip install -r requirements.txt`. On my Mac that `pip`
belongs to the system Python 3.9, while `python` is my conda Python 3.13, so `homework_demo.py` failed with
`ModuleNotFoundError: No module named 'confluent_kafka'`. The AI's requirements file also pinned `requests==2.32.3`, which
downgraded `requests` and conflicted with `snowflake-connector-python` (pip printed an incompatibility warning).

**Independently verified:** I did not take the failure-handling claims on trust. I ran each failure scenario twice against the
real Kafka broker, once without the fix and once with it, and compared the numbers in the logs (see the failure table).

## 3. How I detected the problem / verified the result

The wrong-Python problem showed up as the `ModuleNotFoundError` traceback in my terminal, and the pip output showed it was
installing into `/Users/svtlys/Library/Python/3.9/...` instead of `/Users/svtlys/miniconda3/lib/python3.13/...`. The requests
conflict was printed by pip itself.

For verification I compared before/after evidence in the real run logs:
- Duplicate delivery: the same `correlation_id` sent twice gave 2 drafts without the fix and 1 draft with it (`DUPLICATE ... skipped` in the log).
- Consumer killed: with the offset committed before processing, the killed Writer (exit code 137) lost the message after the restart (committed offset 8, no draft); with commit-after-success the message was redelivered and the offset moved to 9.
- Poison message: unbounded retries gave 149 failed attempts and 0 of 2 later messages processed; bounded retries gave 3 attempts, 1 message in `s8110_dead_letter`, and 2 of 2 later messages processed.
- Ordering: without a key, 3 of 4 entities were processed out of order and spread over 2 partitions; with key = entity_id, all 4 stayed in one partition and in order.

I also ran into one mistake of my own: my `writer.py` was not the right file (the Writer terminal printed `planner starting`), so
nothing read `s8110_tasks` and the pipeline stalled. I noticed it from that log line and replaced the file.

## 4. What I changed and why it works now

- I installed with `python -m pip install -r requirements.txt`, so the packages go into the same Python that runs my scripts, and I relaxed the `requests` pin to `>=2.32.4` to match the other package in my environment.
- I replaced `writer.py` with the correct file; the Writer then printed `writer starting`, picked up the waiting plan from `s8110_tasks`, and the pipeline returned `status: approved` with the original `correlation_id`.
- The fixes for Part 3 (idempotency check on `correlation_id`, offset commit only after success, bounded retries plus `s8110_dead_letter`, and message key = `entity_id`) work because each one removed the failure I measured in the "before" run, and the "after" run logs show the new behavior (single draft, redelivery, dead-letter plus later messages processed, entities in order).
- One limit I am aware of: the unkeyed ordering run sends each message to a seeded random partition (a stand-in for sending without a key), and the idempotency store is a per-agent file, so it only protects a single agent process's own history.