from answering_agent import AnsweringAgent, real_model
from evaluator_agent import Evaluator
from lessons import LessonStore
from pipeline4 import DATA, load_json, run_item, save_raw, setup_logging


def judge(lesson: dict, before: list[dict], after: list[dict]) -> dict:
    """Decide keep/remove for one lesson from before/after single-attempt validation results."""
    fail_b, fail_a = sum(not r["correct"] for r in before), sum(not r["correct"] for r in after)
    regressions = [b["id"] for b, a in zip(before, after) if b["correct"] and not a["correct"]]
    fixed = [b["id"] for b, a in zip(before, after) if not b["correct"] and a["correct"]]
    unsupported = [a["id"] for a in after if a["final_pattern"] == "unsupported_answer"]
    keep = fail_a <= fail_b and not regressions and not unsupported
    reason = "failures improved or unchanged, no regressions" if keep else (
        f"failures {fail_b}->{fail_a}; regressions {regressions}; unsupported answers {unsupported}")
    return {"lesson_id": lesson["lesson_id"], "failure_pattern": lesson["failure_pattern"], "failures_before": fail_b, "failures_after": fail_a,
            "fixed": fixed, "regressions": regressions, "unsupported_answers": unsupported, "keep": keep, "reason": reason}


def validate_one(lesson: dict, items: list[dict], ads: dict, evaluator: Evaluator, before: list[dict], model) -> dict:
    """Run the validation set with only this lesson loaded and judge it."""
    store = LessonStore([dict(lesson)])
    agent = AnsweringAgent(model, ads, store)
    after = [run_item(it, agent, evaluator, use_repair=False) for it in items]
    return judge(lesson, before, after) | {"after_results": [{"id": a["id"], "answer": a["final_answer"], "correct": a["correct"]} for a in after]}


def main() -> None:
    setup_logging()
    reference, ads, val = load_json("reference_dataset.json"), load_json("listing_ads.json"), load_json("validation_data.json")
    candidates, model, evaluator = LessonStore.load(DATA / "lessons_candidates.json"), real_model(), Evaluator(reference)
    base_agent = AnsweringAgent(model, ads, None)
    before = [run_item(it, base_agent, evaluator, use_repair=False) for it in val]
    print(f"validation questions: {len(val)}  baseline failures (no lessons): {sum(not r['correct'] for r in before)}")
    reports, kept, removed = [], LessonStore(), LessonStore()
    for lesson in candidates.lessons:
        rep = validate_one(lesson, val, ads, evaluator, before, model)
        reports.append(rep)
        (kept if rep["keep"] else removed).lessons.append(lesson)
        print(f"{lesson['lesson_id']} {lesson['failure_pattern']:<26} before={rep['failures_before']} after={rep['failures_after']} -> {'KEEP' if rep['keep'] else 'REMOVE'} ({rep['reason']})")
    kept.save(DATA / "lessons.json")
    removed.save(DATA / "lessons_removed.json")
    save_raw("validation_report.json", {"baseline_results": [{"id": b["id"], "answer": b["final_answer"], "correct": b["correct"]} for b in before], "lessons": reports})
    print(f"kept {len(kept.lessons)}, removed {len(removed.lessons)}")


if __name__ == "__main__":
    main()