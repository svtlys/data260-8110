
## 1. What I used an AI assistant for, and what I did myself

Clause was used for dubugging and helping to create skeleton code for Sections 3 and 4. I was able to complete the rest of the code files and complete all other testing being done. Claude also helped in creating the verification file for HW9.

## 2. One AI output that was wrong/unsuitable, and one thing I independently verified

**Wrong/unsuitable:** the instructions for connecting to the database used the wrong environment variable. My `db.py` reads
`MYSQL_ROOT_PASSWORD`, but I first set a different variable, so MySQL answered `Access denied ... (using password: NO)`. A second
mistake: after HW8 I was told the agents did not need to keep running, so I stopped them, and `run_sweep.py` then waited and timed out
because nothing was answering on `s8110_inbox`. A third: the first version of Part 4 `lesson_001` was meant to help, but it made a
move-in answer worse (see section 4).

**Independently verified:** I did not take the cache claims on trust. For the false hit I compared the cached answer with what the
database says for the listing that was actually asked about (the output prints both). For the stale answer I changed the row to 0 units
and checked that the cached answer still said 3 before the fix and the database value afterwards. For Part 4 I compared each lesson against
a no-lesson baseline on the validation questions instead of assuming a lesson helps.

## 3. How I detected the problem / verified the result

- The wrong database variable showed up as the MySQL access-denied error with `using password: NO`; I then looked at the first lines of
  `db.py` to see the variable name it really reads.
- The sweep problem showed up as a timeout traceback; the Planner, Writer and Reviewer terminals were not running.
- Other mistakes were visible in the terminal: commands run from the repo root instead of `code/` (`planner` not found), and a missing module
  (`No module named 'vector_store'`) because a file had not been copied into `code/`.
- Part 4: validation printed `lesson_001 stale_price before=0 after=1 -> REMOVE` with regression `va09` (a move-in total became `wrong_total`).
  The test table showed that the "Validated Improvement" variant loaded only the control lesson yet still scored 20/20, so I do not claim the lessons caused the gain.
- `verify_hw09.py` re-checks the evidence files, the 40-case labeled set, that `cache_cases.yaml` was committed before the sweep result,
  that no dataset contains answers, that no lesson comes from test questions, and that no question used more than 2 attempts.

## 4. What I changed and why it works now

- I exported `MYSQL_ROOT_PASSWORD` in each terminal that touches the database, and I kept the three agents running during `run_part2.py`,
  `run_sweep.py` and `run_stale_demo.py`; after that the pipeline answered and the results were saved to `reports/hw09/raw/`.
- I ran scripts from `code/` and copied the missing files into it.
- Part 4: the validation gate removed the harmful `lesson_001` (documented in `lessons_removed.json`). The stale-price failures that created it
  were injected on purpose (qwen3:8b made no mistakes on the 12 training questions), and the harmful "always give a number" lesson was added on
  purpose to test the gate. These are controlled test cases and are labeled that way in the code, data and report.
- Limits I am aware of: the same rule-based Evaluator both repairs and scores answers, so repair results are optimistic; the validation set
  had 0 baseline failures, so it could not expose the harmful control lesson and the gate kept it; and 20 test questions are too few to
  separate Lesson Memory from Validated Improvement. Threshold choice in Part 3 depends on the cost numbers I assumed, and a threshold alone
  could not stop false hits between listings whose questions differ only in the listing code.