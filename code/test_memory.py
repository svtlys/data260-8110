import tempfile
from pathlib import Path

from memory_config import MemoryConfig
from memory_embed import HashEmbedder
from memory_fakes import FakeStore, fake_llm
from memory_service import MemoryService

tmp = Path(tempfile.mkdtemp()) / "tok.csv"
cfg = MemoryConfig(short_term_n=4, summarize_every=6, top_k=3, policy="full")
svc = MemoryService(FakeStore(), HashEmbedder(), fake_llm, cfg, log_path=tmp)
U, S = "t1", "s1"
msgs = ["Hi, I'm looking for an apartment in Willow Glen.",
        "My budget is $2,400 a month at most.",
        "I have two dogs named Miso and Maxx.",
        "What neighborhoods are quiet?", "I need to move in by December 1.",
        "Do you know about parking?", "Tell me about laundry.", "What about pets deposits?",
        "I work nights at a hospital.", "Any near Caltrain?", "How do leases work?", "Thanks!"]
for i, m in enumerate(msgs, 1):
    r = svc.chat(U, m, S, turn=i)
assert svc.store.count_messages(U, S, "user") == 12 and len(svc.store.msgs) == 24
assert r["memory_used"]["short_term_messages"] == 4
assert svc.store.latest_summary(U, "session", S)["user_msgs_covered"] == 12
assert svc.store.latest_summary(U, "lifetime") is not None
print("facts:", [e["fact"] for e in svc.store.all_episodes(U)])
q = svc.chat(U, "What is my monthly budget?", S, persist=False)
hits = [f["fact"] for f in q["memory_used"]["episodic_facts"]]
print("budget recall:", hits)
assert any("2,400" in h for h in hits)
assert len(svc.store.msgs) == 24                      
kinds = [r["kind"] for r in svc.rows]
assert kinds.count("chat") == 12 and kinds.count("summarize") == 2 and kinds.count("probe") == 1
assert tmp.exists() and len(tmp.read_text().splitlines()) == len(svc.rows) + 1
v = svc.memory_view(U); assert len(v["recent_messages"]) == 16 and v["lifetime_summary"]
a = svc.aggregate(U); assert a["daily_counts"][0]["user"] == 12
# fifo policy: no summaries, no episodic
svc2 = MemoryService(FakeStore(), HashEmbedder(), fake_llm, cfg, log_path=tmp, log=False)
fc = MemoryConfig(short_term_n=4, policy="fifo")
for m in msgs: r2 = svc2.chat(U, m, S, cfg=fc)
assert not svc2.store.sums and not svc2.store.eps and r2["memory_used"]["episodic_facts"] == []
print("ALL OFFLINE MEMORY TESTS PASSED")