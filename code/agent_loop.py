import json
import logging
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import SYSTEM_PROMPT, _parse_action  # noqa: E402
from tool_executor import SAFETY_PREFIX, execute_tool  # noqa: E402

logger = logging.getLogger("agent_loop")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = ROOT / "reports/hw07/raw/agent_runs.jsonl"
MAX_STEPS = 8
MAX_FAILED_REPAIRS = 2

MALFORMED = "malformed_arguments"
UNKNOWN = "unknown_tool"
TEXT = "text_instead_of_tool"
OK_CALL = "ok_call"
FINAL = "final"

MALFORMED_MARKERS = (
    "unexpected input", "missing required", "inputs must be", "is not an allowed input",
    "must be a non-empty string", "must be an integer", "must be >=", "must be <=", "must be at most",
)

LOOP_PROMPT = SYSTEM_PROMPT + (
    "\nFinish the whole task before you answer: call one tool at a time and use each result "
    "to decide the next call. Answer only after you have every fact you need."
    "\nA search result shows only a landlord_id, never the landlord's name. Only get_listing_detail "
    "returns the landlord's name and email, so call it for every listing you are asked about "
    "before you answer."
)
REPAIR_TEXT = (
    "Your last reply was not accepted: {problem}. "
    "Reply again with exactly one JSON object in the format described, using only the listed tools."
)


@dataclass
class ModelReply:
    """One model reply plus its token counts."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class _ToolRoleLLM:
    """Wraps ChatOllama so ("tool", text) tuples become LangChain ToolMessages."""

    def __init__(self, llm) -> None:
        self._llm = llm

    def invoke(self, formatted: list):
        from langchain_core.messages import ToolMessage

        converted = [
            ToolMessage(content=text, tool_call_id=f"call_{i}") if role == "tool" else (role, text)
            for i, (role, text) in enumerate(formatted)
        ]
        return self._llm.invoke(converted)


def _build_llm(model: str, temperature: float, seed):
    """ChatOllama with thinking off (HW6 finding) and an optional seed."""
    from langchain_ollama import ChatOllama

    options = {"model": model, "temperature": temperature}
    if seed is not None:
        options["seed"] = seed
    try:
        return ChatOllama(reasoning=False, **options)
    except TypeError:  # older langchain-ollama without the reasoning switch
        return ChatOllama(**options)


class OllamaModel:
    """The local model, reached through the HW1 ModelClient adapter."""

    def __init__(self, model: str = "qwen3:8b", temperature: float = 0.0, seed=None) -> None:
        self.model = model
        self.temperature = temperature
        self.seed = seed

    def reply(self, messages: list) -> ModelReply:
        """Send the whole conversation to the model and return its reply."""
        sys.path.insert(0, str(ROOT / "src"))
        from model_client import ModelClient

        client = ModelClient(model=self.model, temperature=self.temperature)
        client._llm = _ToolRoleLLM(_build_llm(self.model, self.temperature, self.seed))
        response = client.complete(messages=messages)
        usage = getattr(response, "usage_metadata", None) or {}
        return ModelReply(response.content, usage.get("input_tokens", 0), usage.get("output_tokens", 0))


class MockModel:
    """Scripted stand-in for the LLM (offline tests). Repeats the last reply when it runs out."""

    def __init__(self, replies) -> None:
        self._replies = [replies] if isinstance(replies, str) else list(replies)
        if not self._replies:
            raise ValueError("MockModel needs at least one reply")
        self.calls = 0
        self.seen: list = []

    def reply(self, messages: list) -> str:
        """Return the next scripted reply and remember the messages it was given."""
        self.seen.append([dict(m) for m in messages])
        text = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return text


def _corrupt(action: dict, kind: str) -> str:
    """Return a broken version of a valid tool-call action."""
    if kind == TEXT:
        return "Sure, I will look that up for you now."
    if kind == UNKNOWN:
        return json.dumps({**action, "tool": action["tool"] + "_v2"})
    inputs = action["inputs"]
    broken = {k: ("abc" if isinstance(v, int) else v) for k, v in inputs.items()}
    return json.dumps({**action, "inputs": broken if broken != inputs else {**inputs, "bogus": 1}})


class FaultInjectingModel:
    """Wraps a model and corrupts a seeded fraction of its tool calls (reliability stress test).

    Used only to exercise the repair path; results from it are always labelled "injected"."""

    KINDS = (UNKNOWN, MALFORMED, TEXT)

    def __init__(self, inner, rate: float, seed: int) -> None:
        self.inner = inner
        self.rate = rate
        self.rng = random.Random(seed)
        self.injected: list = []

    def reply(self, messages: list) -> ModelReply:
        """Ask the inner model, then maybe corrupt a valid tool call."""
        reply = _as_reply(self.inner.reply(messages))
        action, _ = _parse_action(reply.text)
        if action is None or action["action"] != "call_tool" or self.rng.random() >= self.rate:
            return reply
        kind = self.rng.choice(self.KINDS)
        self.injected.append(kind)
        return ModelReply(_corrupt(action, kind), reply.input_tokens, reply.output_tokens)


@dataclass
class RunState:
    """Everything one run accumulates."""

    run_id: str
    scenario: str | None
    log_path: object
    messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    steps: int = 0
    tool_calls: int = 0
    failed_repairs: int = 0
    awaiting_repair: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    final_answer: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(state: RunState, kind: str, **fields) -> None:
    """Append one JSON line to the run log (skipped when log_path is None)."""
    if state.log_path is None:
        return
    path = Path(state.log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"run_id": state.run_id, "scenario": state.scenario, "type": kind, "ts": _now(), **fields}
    with open(path, "a") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def classify_tool_error(error) -> str | None:
    """Return MALFORMED / UNKNOWN for a call the tool layer rejected, else None.

    "listing 5 not found" or a safety block is a normal tool outcome, not a bad call."""
    text = str(error or "")
    if text.startswith("unknown tool"):
        return UNKNOWN
    if any(marker in text for marker in MALFORMED_MARKERS):
        return MALFORMED
    return None


def _event(state: RunState, kind: str, **extra) -> None:
    state.events.append({"step": state.steps, "kind": kind, "after_repair": state.awaiting_repair, **extra})


def _register_bad(state: RunState, kind: str, problem: str):
    """Record a bad reply, send the one reprompt, and return "repair_failed" when the bound is hit."""
    _event(state, kind, problem=problem)
    if state.awaiting_repair:
        state.failed_repairs += 1
        state.awaiting_repair = False
        if state.failed_repairs >= MAX_FAILED_REPAIRS:
            return "repair_failed"
    else:
        state.awaiting_repair = True
    state.messages.append({"role": "user", "content": REPAIR_TEXT.format(problem=problem)})
    return None


def _bad_reply(state: RunState, raw: str, problem: str):
    kind = TEXT if "no JSON object" in problem else MALFORMED
    _log(state, "step", step=state.steps, action="invalid_reply", model_output=raw, problem=problem)
    logger.info("[%s] step %d: unusable reply (%s): %s", state.run_id, state.steps, kind, problem)
    state.messages.append({"role": "assistant", "content": raw})
    return _register_bad(state, kind, problem)


def _final_reply(state: RunState, action: dict, raw: str):
    _event(state, FINAL)
    state.awaiting_repair = False
    state.final_answer = action["answer"]
    _log(state, "step", step=state.steps, action="final", model_output=raw, final_answer=state.final_answer)
    return "final_answer"


def _tool_reply(state: RunState, action: dict, raw: str, registry, db):
    state.tool_calls += 1
    logger.info("[%s] tool call %d: %s %s", state.run_id, state.tool_calls, action["tool"],
                json.dumps(action["inputs"]))
    result_json = execute_tool(action["tool"], action["inputs"], db=db, registry=registry)
    envelope = json.loads(result_json)
    bad_kind = None if envelope["ok"] else classify_tool_error(envelope["error"])
    state.trace.append({"n": state.tool_calls, "tool": action["tool"], "inputs": action["inputs"],
                        "ok": envelope["ok"], "rejected": bad_kind, "result": envelope})
    logger.info("[%s]   -> ok=%s %s", state.run_id, envelope["ok"], result_json[:140])
    _log(state, "step", step=state.steps, action="call_tool", model_output=raw, tool=action["tool"],
         inputs=action["inputs"], result=envelope, rejected=bad_kind)
    if not envelope["ok"] and str(envelope["error"]).startswith(SAFETY_PREFIX):
        state.final_answer = envelope["error"]
        return "safety_block"
    state.messages += [{"role": "assistant", "content": raw},
                       {"role": "tool", "name": action["tool"], "content": result_json}]
    if bad_kind:
        return _register_bad(state, bad_kind, str(envelope["error"]))
    _event(state, OK_CALL, tool=action["tool"])
    state.awaiting_repair = False
    return None


def _as_reply(value) -> ModelReply:
    return value if isinstance(value, ModelReply) else ModelReply(str(value))


def _one_step(state: RunState, model, registry, db):
    """Run one model call and act on it. Returns a stop reason, or None to keep going."""
    state.steps += 1
    try:
        reply = _as_reply(model.reply(state.messages))
    except Exception as exc:  # e.g. Ollama is not running
        _log(state, "step", step=state.steps, action="model_error", error=f"{type(exc).__name__}: {exc}")
        return "model_error"
    state.input_tokens += reply.input_tokens
    state.output_tokens += reply.output_tokens
    action, problem = _parse_action(reply.text)
    if action is None:
        return _bad_reply(state, reply.text, problem)
    if action["action"] == "final":
        return _final_reply(state, action, reply.text)
    return _tool_reply(state, action, reply.text, registry, db)


def _finish(state: RunState, stop_reason: str, started: float) -> dict:
    accepted = sum(1 for t in state.trace if not t["rejected"])
    result = {
        "run_id": state.run_id, "scenario": state.scenario, "stop_reason": stop_reason,
        "steps": state.steps, "tool_calls": state.tool_calls, "tool_calls_accepted": accepted,
        "failed_repairs": state.failed_repairs, "final_answer": state.final_answer,
        "events": state.events, "trace": state.trace,
        "input_tokens": state.input_tokens, "output_tokens": state.output_tokens,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }
    _log(state, "stop", **{k: v for k, v in result.items() if k not in ("trace", "events")})
    logger.info("[%s] DONE stop_reason=%s total_tool_calls=%d (accepted %d, rejected %d) steps=%d",
                state.run_id, stop_reason, state.tool_calls, accepted, state.tool_calls - accepted, state.steps)
    return result


def _budget_stop(state: RunState, max_tool_calls, max_total_tokens):
    """Return "tool_budget" / "token_budget" when a hard budget is used up, else None."""
    if max_tool_calls is not None and state.tool_calls >= max_tool_calls:
        return "tool_budget"
    if max_total_tokens is not None and state.input_tokens + state.output_tokens >= max_total_tokens:
        return "token_budget"
    return None


def run_agent(user_input, *, model=None, max_steps: int = MAX_STEPS, registry=None, db=None,
              log_path=DEFAULT_LOG_PATH, run_id=None, scenario=None, notes: str | None = None,
              max_tool_calls: int | None = None, max_total_tokens: int | None = None) -> dict:
    """Run one agent session and return a result dict (stop_reason, tool_calls, final_answer, trace...).

    `notes` is optional untrusted text (Part 3 reflections) shown to the model as quoted data.
    `max_tool_calls` / `max_total_tokens` are hard budgets, checked before every model call."""
    if not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be an integer >= 1")
    started = time.perf_counter()
    state = RunState(run_id or uuid.uuid4().hex[:12], scenario, log_path)
    if not isinstance(user_input, str) or not user_input.strip():
        _log(state, "start", user_input=user_input, max_steps=max_steps)
        return _finish(state, "invalid_input", started)
    content = user_input if not notes else f"{user_input}\n\n{notes}"
    state.messages = [{"role": "system", "content": LOOP_PROMPT}, {"role": "user", "content": content}]
    _log(state, "start", user_input=user_input, max_steps=max_steps, has_notes=bool(notes))
    model = model if model is not None else OllamaModel()
    for _ in range(max_steps):
        stop = _budget_stop(state, max_tool_calls, max_total_tokens) or _one_step(state, model, registry, db)
        if stop:
            return _finish(state, stop, started)
    return _finish(state, "max_steps", started)