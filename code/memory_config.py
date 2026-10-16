import os
from dataclasses import dataclass

# policy -> (use_summaries, use_episodic)
POLICIES = {
    "fifo": (False, False),     # sliding window only: old messages are simply evicted
    "summary": (True, False),   # window + session/lifetime summaries
    "full": (True, True),       # window + summaries + episodic facts (default)
}


@dataclass(frozen=True)
class MemoryConfig:
    short_term_n: int = int(os.environ.get("SHORT_TERM_N", 12)) 
    summarize_every: int = int(os.environ.get("SUMMARIZE_EVERY_USER_MSGS", 6))
    top_k: int = int(os.environ.get("TOP_K", 3))
    min_score: float = 0.2            
    policy: str = os.environ.get("MEMORY_POLICY", "full")
    model: str = os.environ.get("CHAT_MODEL", "qwen3:8b")
    view_messages: int = 16        
    view_facts: int = 20


DEFAULT = MemoryConfig()