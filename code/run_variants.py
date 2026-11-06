from answering_agent import AnsweringAgent, real_model
from evaluator_agent import Evaluator
from lessons import LessonStore
from pipeline4 import DATA, RAW, load_json, run_set, save_raw, setup_logging


def summarize(name: str, results: list[dict]) -> dict:
    """One table row."""
    n = len(results)
    ok = sum(r["correct"] for r in results)
    return {"variant": name, "correct": ok, "incorrect": n - ok, "avg_attempts": round(sum(r["n_attempts"] for r in results) / n, 2),
            "avg_latency_s": round(sum(r["latency_s"] for r in results) / n, 2)}


def table_md(rows: list[dict]) -> str:
    """Markdown results table."""
    lines = ["| Variant | Correct | Incorrect | Average attempts | Average latency (s) |", "|---|---|---|---|---|"]
    lines += [f"| {r['variant']} | {r['correct']} | {r['incorrect']} | {r['avg_attempts']} | {r['avg_latency_s']} |" for r in rows]
    return "\n".join(lines)


def main() -> None:
    setup_logging()
    reference, ads, test = load_json("reference_dataset.json"), load_json("listing_ads.json"), load_json("test_data.json")
    evaluator, model = Evaluator(reference), real_model()
    candidates, validated = LessonStore.load(DATA / "lessons_candidates.json"), LessonStore.load(DATA / "lessons.json")
    plan = [("Baseline", None, False), ("Evaluator Repair", None, True),
            ("Lesson Memory", candidates.copy(), True), ("Validated Improvement", validated.copy(), True)]
    rows, detail = [], {}
    for name, store, repair in plan:
        results = run_set(test, AnsweringAgent(model, ads, store), evaluator, repair)
        rows.append(summarize(name, results))
        detail[name] = {"results": results, "lessons_loaded": [les["lesson_id"] for les in store.lessons] if store else []}
        print(f"{name}: {rows[-1]}")
    save_raw("variant_results.json", {"table": rows, "detail": detail})
    (RAW / "variant_table.md").write_text(table_md(rows), encoding="utf-8")
    print("\n" + table_md(rows))


if __name__ == "__main__":
    main()