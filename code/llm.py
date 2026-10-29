import logging
import os
import re

from kafka_config import LLM_MODEL, SEED

logger = logging.getLogger("llm")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_STEPS = ["Identify what the renter needs to know", "Collect the key facts and risks", "Summarize clearly with next actions"]


def stub_text(prompt: str) -> str:
    """Deterministic placeholder answer derived from the prompt."""
    first = prompt.strip().splitlines()[-1][:120]
    return f"Stub answer based on: {first}. Check the lease terms, the deposit, fees and the move-in condition."


def _ollama(prompt: str, timeout: float = 180.0) -> str:
    import requests

    body = {"model": LLM_MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": 0, "seed": SEED, "num_predict": 300}}
    reply = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=timeout)
    reply.raise_for_status()
    return re.sub(r"<think>.*?</think>", "", reply.json()["response"], flags=re.S).strip()


def generate(prompt: str) -> tuple:
    """(text, source) where source is the model name or 'stub'."""
    if os.environ.get("LLM_MODE", "ollama") == "stub":
        return stub_text(prompt), "stub"
    try:
        return _ollama(prompt), LLM_MODEL
    except Exception as exc:  # network/model errors: fall back visibly
        logger.warning("Ollama unavailable (%s) - using stub text", exc)
        return stub_text(prompt), "stub"


def parse_steps(text: str) -> list:
    """Numbered or dashed lines -> clean step strings (at most 4)."""
    steps = [re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\s*(?:\d+[.)]|[-*])\s+\S", ln)]
    return steps[:4]


def plan_steps(question: str) -> tuple:
    """Planner brain: (list of steps, source)."""
    text, source = generate(f"Break this rental-housing question into 3 short numbered steps. Steps only.\nQuestion: {question}")
    return parse_steps(text) or list(DEFAULT_STEPS), source


def write_draft(question: str, plan: list) -> tuple:
    """Writer brain: (draft answer, source)."""
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(plan, 1))
    return generate(f"Write a short, practical answer (under 120 words) to the question, following the plan.\nPlan:\n{steps}\nQuestion: {question}")