import re
from collections.abc import Callable

from lessons import LessonStore, classify_question

THINK = re.compile(r"<think>.*?</think>", re.S)


def real_model() -> Callable[[str], str]:
    """The real local model call; raises on failure so a broken Ollama is never hidden by a stub."""
    import llm
    return llm._ollama


def clean(text: str) -> str:
    """Remove qwen3 <think> blocks and surrounding whitespace."""
    return THINK.sub("", text).strip()


def build_prompt(ad: str, question: str, lessons: list[dict], prior: str | None, feedback: str | None) -> str:
    """Prompt = instructions + lessons + listing ad + question (+ previous answer and Evaluator feedback on a revision)."""
    parts = ["/no_think", "You are a rental-listing assistant. Answer ONLY from the listing ad below, in one or two short sentences."]
    if lessons:
        parts.append("Lessons learned from earlier mistakes:\n" + "\n".join(f"- {les['correction']}" for les in lessons))
    parts += [f"Listing ad: {ad}", f"Question: {question}"]
    if prior is not None:
        parts += [f"Your previous answer: {prior}", f"Evaluator feedback: {feedback}", "Write a corrected answer."]
    return "\n\n".join(parts) + "\n\nAnswer:"


class AnsweringAgent:
    """Answers questions; loads relevant lessons from the store before answering."""

    def __init__(self, model: Callable[[str], str], ads: dict, store: LessonStore | None = None) -> None:
        self.model, self.ads, self.store = model, ads, store
        self.last_lesson_ids: list[str] = []

    def answer(self, item: dict, prior: str | None = None, feedback: str | None = None) -> str:
        """Return an answer; on the first attempt the lessons used get use_count + 1."""
        lessons = self.store.relevant(classify_question(item["question"])) if self.store else []
        self.last_lesson_ids = [les["lesson_id"] for les in lessons]
        if prior is None and self.store:
            self.store.mark_used(self.last_lesson_ids)
        prompt = build_prompt(self.ads[item["listing_id"]], item["question"], lessons, prior, feedback)
        return clean(self.model(prompt))