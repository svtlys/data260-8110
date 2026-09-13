1. **What I used an AI assistant for, and what I did myself:**

I used Claude to help scaffold the FastAPI backend, the LangGraph supervisor graph structure,
and the three experiment scripts for Part 4. I wrote and adjusted the actual HTML/CSS for the
responsive layout and state handling myself, tested every endpoint and the graph's behavior in
my own terminal and browser, and made the calls on what the adversarial input should look like
and how to interpret the experiment results. I had Claude help create the verify_HW2.py file.  
I also did all the debugging myself when things didn't work as expected.

2. **One AI-produced output that was wrong/unsuitable, or one thing I independently verified:**

My first attempt at the schema validation experiment showed the Planner passing on the first
try in all 30 runs, which seemed suspiciously clean. I verified this wasn't a bug by checking 
the raw JSON/CSV output files directly and confirming the attempt counts matched what was 
printed to console, rather than just trusting the summary numbers Claude helped me compute.

3. **How I detected the problem or verified the result:**

I ran `cat` on the raw results files and manually checked a few entries against the console
output to make sure the classification logic (valid first attempt vs retries vs abandoned) was
actually counting things correctly, not just always reporting the same category by accident.

4. **What I changed and why it works now:**

I didn't need to change the classification logic since it checked out correctly. The model
genuinely did pass validation on the first attempt in all 30 runs for the frozen input. This
pushed me to design a more adversarial input for requirement 5 specifically to actually see
failures, which did produce real retry and ceiling-hit behavior once I made the input harder.