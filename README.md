Part 4 - Report

- Why is prior conversation context resent with every turn? 
The model doesn't actually remember anything between calls. Every request is totally fresh. So the only way it "knows" what we talked about earlier is if I resend the whole conversation history every single time. My ModelClient does this by keeping a running list and sending the entire thing on every call.

- How is a system prompt different from a user message? 
The system prompt sets a standing rule for the whole conversation and stays the same the entire time, I only add it once, at the very start. A user message is just what I'm asking in that specific turn, and it changes every time.

- Why do input tokens grow over a conversation? 
I'm resending the whole history each turn, not just my new message. By turn 5 I'm sending everything from turns 1-4 plus my new message. It keeps stacking up even if each individual message is short.

- What eventually limits that growth?
The context window which tells you how many tokens the model can handle per request. 
