import json

from answering_agent import AnsweringAgent, real_model
from evaluator_agent import Evaluator
from lessons import LessonStore
from pipeline4 import DATA, load_json, run_item, save_raw, setup_logging

CONTROLLED = {"id": "demo_ctrl", "listing_id": "L201", "question": "What is the current monthly rent for listing L201?"}
LATER = {"id": "demo_reuse", "listing_id": "L211", "question": "How much is the monthly rent for listing L211 today?"}
BAD_FIRST = "The rent is $2,400 per month."


def show_sequence(res: dict) -> None:
    """Print one revision sequence."""
    print(f"Question: {res['question']}")
    for a in res["attempts"]:
        print(f"  Attempt {a['attempt']} answer : {a['answer']}")
        print(f"            Evaluator  : {a['verdict']} - {a['explanation']}")
        if a["feedback"]:
            print(f"            Feedback   : {a['feedback']}")
    print(f"  Attempts: {res['n_attempts']}   Final verdict: {res['final_verdict']}   Final response: {res['final_answer']}")


def main() -> None:
    setup_logging()
    reference, ads = load_json("reference_dataset.json"), load_json("listing_ads.json")
    evaluator, model = Evaluator(reference), real_model()
    print("=== A. Controlled revision case (intentionally incorrect first answer) ===")
    res_a = run_item(CONTROLLED, AnsweringAgent(model, ads, None), evaluator, use_repair=True, first_answer_override=BAD_FIRST)
    show_sequence(res_a)
    print("\n=== B. Lesson reuse on a later related question ===")
    store = LessonStore.load(DATA / "lessons.json")
    before = {les["lesson_id"]: les["use_count"] for les in store.lessons}
    plain = run_item(LATER, AnsweringAgent(model, ads, None), evaluator, use_repair=False)
    with_l = run_item(LATER, AnsweringAgent(model, ads, store), evaluator, use_repair=True)
    print(f"Question: {LATER['question']}")
    print(f"  Without lessons: {plain['final_answer']}  -> {plain['final_verdict']}")
    print(f"  Lessons loaded : {with_l['lessons_used'] or 'none apply to this question type'}")
    print(f"  With lessons   : {with_l['final_answer']}  -> {with_l['final_verdict']} (attempts: {with_l['n_attempts']})")
    for les in store.lessons:
        if les["lesson_id"] in with_l["lessons_used"]:
            print(f"  {les['lesson_id']} ({les['failure_pattern']}) use_count {before[les['lesson_id']]} -> {les['use_count']}")
    store.save(DATA / "lessons.json")
    save_raw("part4_demo.json", {"controlled_revision": res_a, "lesson_reuse": {"without_lessons": plain, "with_lessons": with_l}})
    print(json.dumps({"saved": "reports/hw09/raw/part4_demo.json"}))


if __name__ == "__main__":
    main()