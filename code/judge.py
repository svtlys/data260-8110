import logging
import os
import re
from dataclasses import dataclass
from importlib import metadata

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

logger = logging.getLogger("judge")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "qwen3:8b")
JUDGE_SEED = 8110
JUDGE_TEMPERATURE = float(os.environ.get("JUDGE_TEMPERATURE", "0"))   # 0 = the documented setting
JUDGE_TIMEOUT_S = float(os.environ.get("JUDGE_TIMEOUT_S", "90"))

STEPS = {
    "plan_quality": [
        "Read the renter's question (input) and the plan (actual output).",
        "Check that the plan breaks the question into concrete steps that would lead to a useful answer.",
        "Check that the steps are specific to this question (not generic filler), logically ordered and not redundant.",
        "Check that no step is unrelated to the question or impossible to carry out.",
        "Give a low score to a useless or irrelevant plan, a middle score to an acceptable but generic plan, and a high score to a clear, specific, well-ordered plan.",
    ],
    "writer_helpfulness": [
        "Read the renter's question (input) and the draft answer (actual output).",
        "Check that the draft answers the question that was asked, directly and without padding.",
        "Check that the statements are accurate. If facts are given in the context, the draft must agree with them and must not invent facts that are not in them; a contradiction or an invented fact deserves a low score.",
        "Check that the draft is practical: a renter could act on it.",
        "Give a low score to a wrong, irrelevant or unusable draft, a middle score to a partly useful one, and a high score to an accurate, complete and practical one.",
    ],
    "final_helpfulness": [
        "Read the renter's question (input) and the final answer (actual output).",
        "Check that the answer is relevant: it addresses the question that was asked.",
        "Check that the answer is helpful: complete enough, clear, concise and practical.",
        "If facts are given in the context, the answer must agree with them and must not add facts that are not in them.",
        "Give a low score to an irrelevant, wrong or unhelpful answer, a middle score to a partly helpful one, and a high score to a relevant, accurate and helpful one.",
    ],
}


class JudgeError(RuntimeError):
    """The judge could not produce a score for one call."""


class JudgeUnavailable(JudgeError):
    """The judge model cannot be reached at all (no point trying the remaining metrics)."""


@dataclass
class JudgeResult:
    score: float          # 1-5 scale
    reason: str
    raw: float | None = None   # GEval's own 0-1 score


def to_scale(geval_score: float) -> float:
    """GEval 0-1 -> the required 1-5 scale."""
    return round(1.0 + 4.0 * float(geval_score), 2)


def settings() -> dict:
    """Judge configuration saved next to every result."""
    try:
        version = metadata.version("deepeval")
    except metadata.PackageNotFoundError:
        version = None
    return {"framework": "deepeval GEval", "deepeval_version": version, "judge_model": JUDGE_MODEL, "temperature": JUDGE_TEMPERATURE, "seed": JUDGE_SEED,
            "think": False, "num_predict": 400, "timeout_s": JUDGE_TIMEOUT_S, "scale": "1-5 = 1 + 4 * GEval score (0-1)",
            "evaluation_steps": STEPS}


def ollama_generate(prompt: str, schema=None) -> str:
    """One bounded call to the local Ollama server. Raises JudgeUnavailable / JudgeError instead of hanging."""
    import requests

    body = {"model": JUDGE_MODEL, "prompt": prompt, "stream": False, "think": False,
            "options": {"temperature": JUDGE_TEMPERATURE, "seed": JUDGE_SEED, "num_predict": 400}}
    if schema is not None:
        body["format"] = schema.model_json_schema()
    try:
        reply = requests.post(f"{OLLAMA_URL}/api/generate", json=body, timeout=JUDGE_TIMEOUT_S)
        reply.raise_for_status()
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise JudgeUnavailable(f"judge model unreachable or too slow ({type(exc).__name__})") from exc
    except requests.RequestException as exc:
        raise JudgeError(f"judge HTTP error: {exc}") from exc
    return re.sub(r"<think>.*?</think>", "", reply.json().get("response", ""), flags=re.S).strip()


def make_model():
    """DeepEval custom model wrapper around the local Ollama call."""
    from deepeval.models import DeepEvalBaseLLM

    class OllamaJudge(DeepEvalBaseLLM):
        def __init__(self) -> None:
            try:
                super().__init__(JUDGE_MODEL)
            except TypeError:
                super().__init__()

        def load_model(self):
            return JUDGE_MODEL

        def generate(self, prompt: str, schema=None):
            text = ollama_generate(prompt, schema)
            return schema.model_validate_json(text) if schema is not None else text

        async def a_generate(self, prompt: str, schema=None):
            return self.generate(prompt, schema)

        def get_model_name(self) -> str:
            return JUDGE_MODEL

    return OllamaJudge()


class DeepEvalJudge:
    """score(metric, question, output, context) -> JudgeResult, using GEval with fixed evaluation steps."""

    def __init__(self) -> None:
        self.model = make_model()

    def score(self, metric: str, question: str, output: str, context: list | None = None) -> JudgeResult:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        params = [LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT] + ([LLMTestCaseParams.CONTEXT] if context else [])
        case = LLMTestCase(input=question, actual_output=output, context=context or None)
        geval = GEval(name=metric, evaluation_steps=STEPS[metric], evaluation_params=params, model=self.model, async_mode=False, verbose_mode=False)
        try:
            geval.measure(case, _show_indicator=False)
        except TypeError:
            geval.measure(case)
        if geval.score is None:
            raise JudgeError("GEval returned no score")
        return JudgeResult(to_scale(geval.score), (geval.reason or "").strip(), float(geval.score))