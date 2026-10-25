import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_cases import (  # noqa: E402
    build_cases_from_rows, load_cases, make_attempt_record, reliability_table,
    summarize_reliability, unsupported_claims,
)
from agent_loop import FaultInjectingModel, OllamaModel, run_agent  # noqa: E402

logger = logging.getLogger("run_hw7_part2")
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "reports/hw07/raw"
CASES_PATH = RAW / "fixed_cases.json"
ATTEMPTS_PATH = RAW / "part2_attempts.jsonl"
SEED = 8110


def _database_rows():
    """Listing rows and landlord names from the real database."""
    from db import db_session_basede26
    from models import Landlord, Listing

    session = db_session_basede26()
    try:
        rows = [{"id": r.id, "address": r.address, "listing_code": r.listing_code,
                 "available_units": r.available_units, "landlord_id": r.landlord_id}
                for r in session.query(Listing).order_by(Listing.id).all()]
        names = {x.id: x.name for x in session.query(Landlord).all()}
    finally:
        session.close()
    return rows, names


def make_cases(_args) -> None:
    """Build the fixed cases from the database and save them."""
    rows, names = _database_rows()
    data = build_cases_from_rows(rows, names, SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    CASES_PATH.write_text(json.dumps(data, indent=2))
    logger.info("saved %d fixed cases + 1 recovery case to %s (term %r)", len(data["cases"]), CASES_PATH,
                data["term"])
    for case in data["cases"] + [data["recovery"]]:
        logger.info("  %s: %s", case["id"], case["prompt"])


def _append(record: dict) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with open(ATTEMPTS_PATH, "a") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


def _run_case(case: dict, index: int, phase: str, model, label: str) -> dict:
    logger.info("=== %s | %s | %s", phase, case["id"], case["title"])
    logger.info("PROMPT: %s", case["prompt"])
    run = run_agent(case["prompt"], model=model, run_id=label, scenario=f"{phase}-{case['id']}")
    record = make_attempt_record(index, case, run)
    record["phase"] = phase
    record["injected"] = list(getattr(model, "injected", []))
    _append(record)
    logger.info("FINAL ANSWER: %s", run["final_answer"])
    verdict = "PASS" if record["check"]["passed"] else "FAIL " + ", ".join(record["check"]["reasons"])
    logger.info("VERIFIER: %s | tool calls: %d | unsupported claims: %s | %d ms",
                verdict, run["tool_calls"], unsupported_claims(run) or "none", run["latency_ms"])
    return record


def run_tasks(args) -> None:
    """Run the three verification tasks once each, at temperature 0."""
    data = load_cases(CASES_PATH)
    model = OllamaModel(temperature=0.0, seed=SEED)
    for case in data["cases"]:
        _run_case(case, 0, "verify", model, f"verify-{case['id']}")


def run_recover(args) -> None:
    """Run the nonexistent-ID case and show the raw tool message."""
    data = load_cases(CASES_PATH)
    case = data["recovery"]
    record = _run_case(case, 0, "recovery", OllamaModel(temperature=0.0, seed=SEED), "recover-E")
    for call in record["trace"]:
        logger.info("execute_tool(%s, %s) ran without crashing", call["tool"], json.dumps(call["inputs"]))
    logger.info("agent stop_reason: %s (no exception raised)", record["run"]["stop_reason"])


def run_reliability(args) -> None:
    """Run N attempts across A, B, C and save raw data plus the summary table."""
    data = load_cases(CASES_PATH)
    injected_run = args.inject_rate > 0
    phase = "reliability_injected" if injected_run else "reliability"
    suffix = "_injected" if injected_run else ""
    attempts = []
    for i in range(args.n):
        case = data["cases"][i % len(data["cases"])]
        model = OllamaModel(temperature=args.temperature, seed=SEED + i)
        if injected_run:
            model = FaultInjectingModel(model, args.inject_rate, SEED + i)
        record = _run_case(case, i, phase, model, f"{'inj' if injected_run else 'rel'}-{i:02d}-{case['id']}")
        attempts.append(record)
        logger.info("attempt %d/%d done | slots first-ok %d/%d | injected faults: %s", i + 1, args.n,
                    sum(s["first_ok"] for s in record["slots"]), len(record["slots"]),
                    record["injected"] or "none")
    summary = summarize_reliability(attempts)
    summary["settings"] = {"model": "qwen3:8b", "temperature": args.temperature, "seed_base": SEED,
                           "seed_rule": "seed = 8110 + attempt index", "max_steps": 8,
                           "inject_rate": args.inject_rate,
                           "injected_faults": sum(len(a["injected"]) for a in attempts)}
    (RAW / f"part2_reliability_summary{suffix}.json").write_text(json.dumps(summary, indent=2))
    table = reliability_table(summary)
    (RAW / f"part2_reliability_table{suffix}.md").write_text(table + "\n")
    logger.info("\n%s", table)
    logger.info("verifier passed %d of %d attempts | injected faults: %d", summary["verifier_passed"],
                summary["attempts"], summary["settings"]["injected_faults"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("make-cases").set_defaults(func=make_cases)
    sub.add_parser("tasks").set_defaults(func=run_tasks)
    sub.add_parser("recover").set_defaults(func=run_recover)
    rel = sub.add_parser("reliability")
    rel.add_argument("--n", type=int, default=21)
    rel.add_argument("--temperature", type=float, default=0.7)
    rel.add_argument("--inject-rate", type=float, default=0.0,
                     help="fraction of tool calls to corrupt on purpose (stress test of the repair path)")
    rel.set_defaults(func=run_reliability)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args.func(args)


if __name__ == "__main__":
    main()