# AI Use: HW7

1. **What I used an AI assistant for, and what I did myself:**

I used Claude to write first drafts of most of the code: the JWT authentication and role checks with the Ruff and pre-commit setup, the hand-written agent loop with its repair path and budgets, the task cases and verifier, the seeded fault injector, the bounded Reflexion module, the LangGraph bike-share agent with its three tools and web page, the data-preparation script, the injection fixtures and judging code, the file tools and the bash safety gate, the offline tests, and `verify_hw07.py`. It also drafted the report text and this file. I installed and ran everything on my own machine, ran every script and test, tested the pages in the browser, took the screenshots, read the saved run files when something looked wrong, chose the pricing page and downloaded the trip data, filled in the prices from the page, and decided what to keep or report.

2. **One AI-produced output that was wrong or unsuitable:**

In my first run of the Part 4 bike-share agent on the pay-per-use data, the agent used all 14 steps and never gave a final answer (the page said "No usable answer: the agent gave no final answer"). Claude's design asked the model to compute both cost totals itself with the calculator, and its page retriever dropped short lines such as `$120/year`, so the model never found the membership price and kept sending near-identical calculator expressions (`520 * 0.15`, then the same expression with one more term added each step) that also left out the $1 unlock fee.

3. **How I detected the problem or verified the result:**

The metrics strip showed 14 steps, 14 tool calls and the stop reason `max_steps`. I listed every tool call from the saved run file: two `policy_retriever` calls followed by twelve `calculator` calls. I searched the saved pricing-page text and found `$120/year` on three lines, so the price was on the page but not in the passages the retriever returned.

4. **What I changed and why it works now:**

The retriever now keeps the neighbouring lines of a short price line, so `Membership | Annual | $120/year` comes back as one passage. The prompt no longer lets the model calculate totals: it gathers the trip statistics and the prices, and the application recomputes both totals in code, with at most 6 tool calls. After these changes both scenarios produced answers. The agent still sometimes chose the wrong decision or the $25 university membership price, so I added a verifier that sends the recomputed totals back once and a price check against the page text. My last Scenario B run, which was made before the price check, still used the $25 price, and the report says so.