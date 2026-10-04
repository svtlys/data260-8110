import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tool_executor import SAFETY_PREFIX, execute_tool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = ROOT / "reports/hw05/raw/agent_runs.jsonl"
DEFAULT_MAX_STEPS = 6

SYSTEM_PROMPT = """You are an assistant for a rental-housing listings database.
You can call these tools:
- search_listings(query: string, limit: integer 1-50, default 10): find listings whose address contains the query.
- get_listing_detail(listing_id: integer >= 1): details of one listing, including its landlord.
- aggregate_landlord_stats(landlord_id: integer >= 1): the number of listings and available units for one landlord.

Reply with ONLY one JSON object per message and no other text:
{"action": "call_tool", "tool": "<tool name>", "inputs": {<arguments>}}
or, when you can answer the user:
{"action": "final", "answer": "<your answer>"}

Tool results come back as JSON envelopes {"ok": ..., "data": ..., "error": ...}.
If ok is false, read the error, then fix your input or explain the problem in your final answer.
Use only information from tool results. Do not invent listings, landlords or numbers."""

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class OllamaModel:
    """The local model, reached through the HW1 adapter in src/model_client.py."""

    def __init__(self, model: str = "qwen3:8b", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def reply(self, messages: list) -> str:
        sys.path.insert(0, str(ROOT / "src"))
        from model_client import ModelClient  # imported lazily: needs langchain + Ollama

        client = ModelClient(model=self.model, temperature=self.temperature)
        response = client.complete(messages=messages)
        return response.content


class MockModel:
    """Scripted stand-in for the LLM, for offline tests. Returns the given
    replies in order and repeats the last one when they run out."""

    def __init__(self, replies):
        self._replies = [replies] if isinstance(replies, str) else list(replies)
        if not self._replies:
            raise ValueError("MockModel needs at least one reply")
        self.calls = 0

    def reply(self, messages: list) -> str:
        index = min(self.calls, len(self._replies) - 1)
        self.calls += 1
        return self._replies[index]


# ----------------------------------------------------------------- helpers

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(path, record: dict) -> None:
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _parse_action(text):
    """Return (action dict, None) or (None, reason the reply was unusable)."""
    cleaned = _THINK_BLOCK.sub("", text or "").strip()
    start = cleaned.find("{")
    if start == -1:
        return None, "the reply contained no JSON object"
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except ValueError:
        return None, "the reply was not valid JSON"
    if not isinstance(obj, dict):
        return None, "the reply must be a JSON object"

    action = obj.get("action")
    if action == "final":
        answer = obj.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return None, "a final reply needs a non-empty string 'answer'"
        return {"action": "final", "answer": answer}, None
    if action == "call_tool":
        tool, inputs = obj.get("tool"), obj.get("inputs", {})
        if not isinstance(tool, str) or not tool.strip():
            return None, "a call_tool reply needs a string 'tool'"
        if not isinstance(inputs, dict):
            return None, "'inputs' must be a JSON object"
        return {"action": "call_tool", "tool": tool, "inputs": inputs}, None
    return None, "'action' must be \"call_tool\" or \"final\""


# ------------------------------------------------------------------- agent

def run_agent(
    user_input,
    *,
    model=None,
    max_steps: int = DEFAULT_MAX_STEPS,
    registry=None,
    db=None,
    log_path=DEFAULT_LOG_PATH,
    run_id=None,
    scenario=None,
) -> dict:
    """Run one agent session and return
    {run_id, stop_reason, steps, tool_calls, final_answer}."""
    if not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be an integer >= 1")
    run_id = run_id or uuid.uuid4().hex[:12]
    base = {"run_id": run_id, "scenario": scenario}
    steps = 0
    tool_calls = 0
    final_answer = None

    def finish(stop_reason: str) -> dict:
        _log(log_path, {**base, "type": "stop", "ts": _now(), "stop_reason": stop_reason,
                        "steps": steps, "tool_calls": tool_calls, "final_answer": final_answer})
        return {"run_id": run_id, "stop_reason": stop_reason, "steps": steps,
                "tool_calls": tool_calls, "final_answer": final_answer}

    if not isinstance(user_input, str) or not user_input.strip():
        _log(log_path, {**base, "type": "start", "ts": _now(), "user_input": user_input,
                        "max_steps": max_steps})
        return finish("invalid_input")

    model = model if model is not None else OllamaModel()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]
    _log(log_path, {**base, "type": "start", "ts": _now(), "user_input": user_input,
                    "max_steps": max_steps})

    for step in range(1, max_steps + 1):
        steps = step
        try:
            raw = model.reply(messages)
        except Exception as exc:  # e.g. Ollama is not running
            _log(log_path, {**base, "type": "step", "ts": _now(), "step": step,
                            "action": "model_error", "error": f"{type(exc).__name__}: {exc}"})
            return finish("model_error")

        action, problem = _parse_action(raw)
        if action is None:
            _log(log_path, {**base, "type": "step", "ts": _now(), "step": step,
                            "action": "invalid_reply", "model_output": raw, "problem": problem})
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your reply was not usable: {problem}. "
                                            "Reply with exactly one JSON object as described."},
            ]
            continue

        if action["action"] == "final":
            final_answer = action["answer"]
            _log(log_path, {**base, "type": "step", "ts": _now(), "step": step,
                            "action": "final", "model_output": raw, "final_answer": final_answer})
            return finish("final_answer")

        tool_calls += 1
        result_json = execute_tool(action["tool"], action["inputs"], db=db, registry=registry)
        envelope = json.loads(result_json)
        _log(log_path, {**base, "type": "step", "ts": _now(), "step": step,
                        "action": "call_tool", "model_output": raw, "tool": action["tool"],
                        "inputs": action["inputs"], "result": envelope})

        if not envelope["ok"] and str(envelope["error"]).startswith(SAFETY_PREFIX):
            final_answer = envelope["error"]
            return finish("safety_block")

        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": f"Tool result for {action['tool']}: {result_json}"},
        ]

    return finish("max_steps")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('usage: python agent.py "your question"')
    summary = run_agent(" ".join(sys.argv[1:]))
    print(json.dumps(summary, indent=2))