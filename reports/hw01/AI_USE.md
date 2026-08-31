# AI Use — HW1

1. **What I used an AI assistant for, and what I did myself:**
I used Claude to  guide me through the AWS ECS deployment, since I have no experience whatsoever. I also had Claude look over the HTML and Javascript files since I had very little experience int hat as well. 

 I wrote the Python files myself — agents_demo.py, run_experiment.py, model_client.py, and hw1_client.py.I also did all the actual command execution, file creation, testing, and debugging myself, including tracking down and fixing issues as they came up.


2. **One AI-produced output that was wrong/unsuitable, or one thing I independently verified:**
My hw1_client.py's /stats and /exit commands weren't actually being recognized — when I typed them, the script sent them to the model as regular messages instead of triggering the intercept logic, so I never got a clean exit or a working stats output during my 5-turn conversation.

3. **How I detected the problem or verified the result:**
I noticed it because the model kept generating full code-review responses to "/stats" and "/exit" instead of printing the expected stats output or quitting. The terminal transcript showed turn 6 and turn 7 both getting real LLM replies instead of the intercepted behavior.

4. **What I changed and why it works now:**
I retyped the commands manually instead of pasting them, which fixed it because pasting was introducing an invisible character that broke the exact string match in the code
