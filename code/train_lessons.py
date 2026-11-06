import argparse
import json

from answering_agent import AnsweringAgent, real_model
from evaluator_agent import Evaluator
from lessons import ALL_CATEGORIES, RISKY_CORRECTION, classify_question, lessons_from_failures
from pipeline4 import DATA, load_json, run_item, save_raw, setup_logging


def stale_answer(ref: dict) -> str:
    """Intentionally wrong first answer (old price) used for controlled failures."""
    return f"The rent is ${ref['previous_rent']:,} per month."


def collect_failures(train: list[dict], answerer, evaluator, reference: dict, inject: bool) -> tuple[list[dict], list[dict]]:
    """First-attempt failures on the training set (optionally with the first two rent items replaced by a stale answer)."""
    results, failures, injected = [], [], 0
    for item in train:
        override = None
        ref = reference[item["listing_id"]]
        if inject and injected < 2 and classify_question(item["question"]) == "rent" and ref["previous_rent"]:
            override, injected = stale_answer(ref), injected + 1
        res = run_item(item, answerer, evaluator, use_repair=False, first_answer_override=override)
        res["injected"] = override is not None
        results.append(res)
        if not res["correct"]:
            failures.append({"id": item["id"], "pattern": res["first_pattern"]})
    return results, failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument("--inject-failures", action="store_true", help="replace the first two rent answers with a stale-price answer (controlled failures)")
    ap.add_argument("--risky-control", action="store_true", help="add one deliberately harmful lesson to test the validation gate")
    args = ap.parse_args()
    setup_logging()
    reference, ads, train = load_json("reference_dataset.json"), load_json("listing_ads.json"), load_json("training_data.json")
    answerer = AnsweringAgent(real_model(), ads, None)
    results, failures = collect_failures(train, answerer, Evaluator(reference), reference, args.inject_failures)
    store = lessons_from_failures(failures, args.min_count)
    if args.risky_control:
        store.add("controlled_risky_rule", RISKY_CORRECTION, ALL_CATEGORIES, source="controlled_test_rule")
    store.save(DATA / "lessons_candidates.json")
    store.save(DATA / "lessons.json")
    save_raw("training_run.json", {"results": results, "failures": failures, "lessons": store.lessons})
    print(f"training questions: {len(train)}  first-attempt failures: {len(failures)}")
    for pat in sorted({f['pattern'] for f in failures}):
        print(f"  {pat}: {sum(1 for f in failures if f['pattern'] == pat)}")
    print(f"lessons written: {len(store.lessons)}")
    print(json.dumps([{k: les[k] for k in ('lesson_id', 'failure_pattern', 'source', 'use_count')} for les in store.lessons], indent=2))


if __name__ == "__main__":
    main()