import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_THINK = re.compile(r"<think>.*?</think>", re.S)
NO_THINK = "\n/no_think"   # qwen3 switch that skips the slow 'thinking' phase


def est_tokens(text: str) -> int:
    return -(-len(text) // 4) if text else 0


_announced = False


def _make_llm(model):
    """ChatOllama with qwen3 'thinking' switched off at the API level (reasoning=False)."""
    global _announced
    from langchain_ollama import ChatOllama
    kwargs = dict(model=model, temperature=0.0)
    ok = "reasoning" in getattr(ChatOllama, "model_fields", {})
    if ok:
        kwargs["reasoning"] = False
    if not _announced:
        print(f"[memory_llm] thinking disabled via reasoning=False: {ok}", flush=True)
        _announced = True
    return ChatOllama(**kwargs)


def call_model(system: str, messages: list, model: str = "qwen3:8b") -> dict:
    """-> {text, prompt_tokens, completion_tokens, latency_ms}"""
    from src.model_client import ModelClient
    client = ModelClient(model=model, temperature=0.0)
    client._llm = _make_llm(model)    # same ModelClient, thinking-free LLM underneath
    client.add_system_message(system)
    t0 = time.perf_counter()
    resp = client.complete(messages=messages)
    latency_ms = (time.perf_counter() - t0) * 1000
    text = _THINK.sub("", resp.content or "").strip()
    pt, ct = client.cumulative_input_tokens, client.cumulative_output_tokens
    if pt == 0:   # usage metadata missing -> estimate
        pt = est_tokens(system) + sum(est_tokens(m["content"]) for m in messages)
        ct = est_tokens(text)
    return {"text": text, "prompt_tokens": pt, "completion_tokens": ct,
            "latency_ms": round(latency_ms, 1)}