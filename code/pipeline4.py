import json
import logging
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "hw09"
RAW = ROOT / "reports" / "hw09" / "raw"
log = logging.getLogger("part4")


def load_json(name: str, folder: Path = DATA):
    """Read a JSON file from data/hw09 (or another folder)."""
    return json.loads((folder / name).read_text(encoding="utf-8"))


def save_raw(name: str, obj) -> Path:
    """Write evidence to reports/hw09/raw/."""
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    return path


def run_item(item: dict, answerer, evaluator, use_repair: bool, max_attempts: int = 2, first_answer_override: str | None = None) -> dict:
    """Answer -> Evaluator verdict -> (feedback -> revised answer -> re-evaluate), stopping at PASS or max_attempts."""
    limit = max_attempts if use_repair else 1
    attempts, prior, feedback, lessons_used = [], None, None, []
    start = time.perf_counter()
    for n in range(1, limit + 1):
        if n == 1 and first_answer_override is not None:
            answer = first_answer_override
        else:
            answer = answerer.answer(item, prior, feedback)
        if n == 1:
            lessons_used = list(answerer.last_lesson_ids)
        ev = evaluator.evaluate(item, answer)
        attempts.append({"attempt": n, "answer": answer, **ev})
        log.info("%s attempt %d -> %s %s", item["id"], n, ev["verdict"], ev["pattern"] or "")
        if ev["verdict"] == "PASS":
            break
        prior, feedback = answer, ev["feedback"]
    final = attempts[-1]
    return {"id": item["id"], "listing_id": item["listing_id"], "question": item["question"], "attempts": attempts, "n_attempts": len(attempts),
            "final_answer": final["answer"], "final_verdict": final["verdict"], "final_pattern": final["pattern"], "correct": final["verdict"] == "PASS",
            "first_attempt_correct": attempts[0]["verdict"] == "PASS", "first_pattern": attempts[0]["pattern"],
            "latency_s": round(time.perf_counter() - start, 3), "lessons_used": lessons_used}


def run_set(items: list[dict], answerer, evaluator, use_repair: bool) -> list[dict]:
    """Run every item of a dataset."""
    return [run_item(it, answerer, evaluator, use_repair) for it in items]


def setup_logging() -> None:
    """Console logging for the Part 4 scripts."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")