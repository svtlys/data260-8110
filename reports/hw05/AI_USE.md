# AI Use: HW5

1. **What I used an AI assistant for, and what I did myself:**

I used Claude to write first drafts of most of the code: the SQLAlchemy models and migration for the landlord table, the Pydantic schemas and FastAPI routes, the Redux Toolkit slice and the updated React components, the two MCP servers and the replay script, the retry/backoff module with the seeded fault injector and its experiment script, `execute_tool` and the safety rule, the offline test runner, the agent loop, and `verify_hw05.py`. It also drafted my write-ups: the tool-contract table, the results analysis, and the reflection. I installed and ran everything on my own machine, set up and fixed MySQL, ran every script and test, tested the endpoints in Postman and the servers in the MCP Inspector, took the screenshots, debugged the problems that came up (a MySQL upgrade that stopped the server and forced a rebuild from my seed scripts, a missing Redux `Provider`, the MySQL password not reaching the Inspector's server process, an MCP SDK version mismatch), and decided what to keep.

2. **One AI-produced output that was wrong or unsuitable:**

My first version of agent scenario 5 was meant to hit the `max_steps` ceiling. It asked the agent to look up listings 1 through 10 with `max_steps` set to 3. The run did not reach the ceiling: the model asked for listing 1, the tool returned `listing 1 not found`, and the model gave up with a final answer after 2 steps. The scenario was named "max_steps ceiling reached" but its recorded stop reason was `final_answer`. The prompt assumed those ids existed in my database, and they did not.

3. **How I detected the problem or verified the result:**

The summary table printed after the run showed `stop_reason=final_answer` with 2 steps for a scenario that was supposed to end at `max_steps`. I read the run in `agent_runs.jsonl`, which showed the `listing 1 not found` error after step 1. I then checked which ids exist, using the listings that appeared in my earlier safety-rule demo (ids 3, 12 and 16). [For the optional note: I compared the agent's answer with `SELECT COUNT(*) FROM listings WHERE address LIKE '%Main%'`.]

4. **What I changed and why it works now:**

I rewrote the prompt to ask for listings 3, 12, 16, 17 and 18, which is more lookups than the ceiling of 3 allows, and renamed the scenario so its name no longer claims an outcome. I also added a way to re-run a single scenario and merge its row into the results file, so I did not have to repeat the whole 10-minute run. The re-run stopped with `max_steps` after 3 steps and 3 tool calls. The first attempt is still in `agent_runs.jsonl` and `RUN_LOG.txt` as a record of what happened. The `max_steps` behavior is also tested deterministically in the offline suite with a `MockModel`, which does not depend on what the real model decides to do.