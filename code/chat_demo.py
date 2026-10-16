import json
import urllib.request

BASE = "http://localhost:8010"
USER = "alex"
MESSAGES = [
    "Hi, I'm looking for an apartment in Willow Glen.",
    "My budget is $2,400 a month at most.",
    "I have two cats named Miso and Pickles.",
    "What should I look for in a lease for pets?",
    "I need to move in by December 1.",
    "Is in-unit laundry common in that area?",
    "I work night shifts at a hospital, so quiet buildings matter to me.",
    "What questions should I ask a landlord on a tour?",
    "I don't want carpet because of my cats.",
    "How big a security deposit is typical?",
    "Remind me: what is my maximum monthly budget?",
    "And what are my cats called?",
]


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


session = None
for i, m in enumerate(MESSAGES, 1):
    r = call("POST", "/api/chat", {"user_id": USER, "message": m, "session_id": session})
    session = r["session_id"]
    mu, u = r["memory_used"], r["usage"]
    print(f"\n[{i}] USER: {m}\n    BOT : {r['reply']}")
    print(f"    memory: window={mu['short_term_messages']} msgs | "
          f"session_summary={'yes' if mu['session_summary'] else 'no'} | "
          f"lifetime={'yes' if mu['lifetime_summary'] else 'no'} | "
          f"facts={[f['fact'][:40] for f in mu['episodic_facts']]}")
    print(f"    tokens: prompt={u['prompt_tokens']} completion={u['completion_tokens']} "
          f"latency={u['latency_ms']:.0f}ms  components={u['components']}")
print("\n=== GET /api/memory/%s ===" % USER)
print(json.dumps(call("GET", f"/api/memory/{USER}"), indent=2)[:3500])
print("\n=== GET /api/aggregate/%s ===" % USER)
print(json.dumps(call("GET", f"/api/aggregate/{USER}"), indent=2)[:2500])