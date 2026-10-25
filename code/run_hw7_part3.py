import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_cases import check_case, load_cases  # noqa: E402
from agent_loop import FaultInjectingModel, OllamaModel, run_agent  # noqa: E402
from reflexion import (  # noqa: E402
    ReflectionStore, attempt_record, comparison_table, false_rejection_candidate, run_with_reflexion,
    summarize_comparison,
)

logger = logging.getLogger("run_hw7_part3")
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "reports/hw07/raw"
CASES_PATH = RAW / "fixed_cases.json"
REFLECTIONS_PATH = RAW / "reflections.jsonl"
TASKS_PATH = RAW / "part3_tasks.jsonl"
LOG_PATH = RAW / "agent_runs_part3.jsonl"
SEED = 8110
USER_ID = "student-8110"


def _factory(args, index: int):
    """make_model(attempt): same settings every time; the seed changes per task and per retry."""
    def make_model(attempt: int):
        seed = SEED + index + 1000 * attempt
        model = OllamaModel(temperature=args.temperature, seed=seed)
        return FaultInjectingModel(model, args.inject_rate, seed) if args.inject_rate > 0 else model
    return make_model


def _one_task(args, case: dict, index: int, store) -> dict:
    make_model = _factory(args, index)
    label = f"{index:02d}-{case['id']}"
    logger.info("=== task %s | %s", label, case["title"])
    run = run_agent(case["prompt"], model=make_model(0), log_path=LOG_PATH, run_id=f"p3-orig-{label}",
                    scenario=f"original-{case['id']}")
    original = attempt_record(0, run, check_case(case, run))
    verdict = "PASS" if original["check"]["passed"] else "FAIL " + ", ".join(original["check"]["reasons"])
    logger.info("ORIGINAL LOOP: %s (stop_reason=%s, %d tool calls)", verdict, run["stop_reason"], run["tool_calls"])
    result = run_with_reflexion(
        case, make_model=make_model, reflect_model=OllamaModel(temperature=0.0, seed=SEED), user_id=USER_ID,
        task_run_id=f"p3-{label}", store=store, first_run=run, tool_budget=args.tool_budget,
        token_budget=args.token_budget, log_path=LOG_PATH)
    logger.info("REFLEXION LOOP: stop=%s retries=%d tool_calls=%d tokens=%d", result["stop_reason"],
                result["retries"], result["tool_calls"], result["tokens"])
    return {"index": index, "case": case["id"], "original": original, "reflexion": result}


def _write_review_file(tasks: list) -> None:
    lines = ["# Possible verifier false rejections (read each answer by hand)", ""]
    for t in tasks:
        attempts = [("original", t["original"])] + [(f"reflexion attempt {a['attempt'] + 1}", a)
                                                    for a in t["reflexion"]["attempts"]]
        for name, a in attempts:
            if false_rejection_candidate(a):
                lines += [f"## task {t['index']:02d} case {t['case']} - {name}",
                          f"verifier reasons: {a['check']['reasons']}",
                          f"final answer: {a['run']['final_answer']}", ""]
    (RAW / "part3_review_candidates.md").write_text("\n".join(lines) + "\n")


def show_reflections(_args) -> None:
    """Print stored reflections with the evidence that triggered them."""
    if not REFLECTIONS_PATH.exists():
        logger.info("no reflections stored yet (%s)", REFLECTIONS_PATH)
        return
    for line in REFLECTIONS_PATH.read_text().splitlines():
        r = json.loads(line)
        logger.info("--- reflection | task %s | case %s | after attempt %d", r["task_run_id"], r["case"],
                    r["after_attempt"] + 1)
        logger.info("failure:  %s", r["failure"])
        logger.info("strategy: %s%s", r["strategy"], "  [fallback used]" if r["strategy_replaced_by_fallback"] else "")
        ev = r["evidence"]
        logger.info("evidence: tool_call=%s", json.dumps(ev["tool_call"]))
        logger.info("          observation=%s", ev["observation"])
        logger.info("          verifier=%s", json.dumps(ev["verifier_result"]))
        logger.info("          stop_reason=%s final_answer=%s", ev["stop_reason"], ev["final_answer"])


def compare(args) -> None:
    """Run both loops on N tasks and save raw data, the comparison table and review candidates."""
    cases = load_cases(CASES_PATH)["cases"]
    store = ReflectionStore(REFLECTIONS_PATH)
    tasks = []
    for i in range(args.n):
        task = _one_task(args, cases[i % len(cases)], i, store)
        tasks.append(task)
        with open(TASKS_PATH, "a") as handle:
            handle.write(json.dumps(task, default=str) + "\n")
    summary = summarize_comparison(tasks)
    summary["settings"] = {"model": "qwen3:8b", "temperature": args.temperature, "inject_rate": args.inject_rate,
                           "seed_rule": "8110 + task index + 1000 * attempt", "max_retries": 2,
                           "tool_budget": args.tool_budget, "token_budget": args.token_budget}
    (RAW / "part3_comparison.json").write_text(json.dumps(summary, indent=2))
    table = comparison_table(summary)
    (RAW / "part3_comparison.md").write_text(table + "\n")
    _write_review_file(tasks)
    logger.info("\n%s", table)
    logger.info("Reflexion stop reasons: %s", summary["reflexion_stop_reasons"])
    show_reflections(args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--n", type=int, default=21)
    cmp_.add_argument("--temperature", type=float, default=0.7)
    cmp_.add_argument("--inject-rate", type=float, default=0.5)
    cmp_.add_argument("--tool-budget", type=int, default=12)
    cmp_.add_argument("--token-budget", type=int, default=8000)
    cmp_.set_defaults(func=compare)
    sub.add_parser("show-reflections").set_defaults(func=show_reflections)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args.func(args)


if __name__ == "__main__":
    main()