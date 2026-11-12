import json
import logging
import sys
from pathlib import Path

from cache_config import SID4, setup_logging
from judge import DeepEvalJudge
from pipeline_eval import evaluate_trace, make_collector
from traced_service import build_service

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw10" / "raw"
QUESTIONS = [
    "What should I check in the lease before signing a one-year rental agreement?",
    "How can I tell whether a landlord is asking for an unreasonable security deposit?",
    "How many units are available at listing S8110-A03?",
    "What is the address of listing S8110-A05?",
    "What can I do if the heater stops working and my landlord does not respond?",
]


def fmt(score) -> str:
    return "  -  " if score is None else f"{score:4.2f}"


def main() -> int:
    setup_logging(logging.INFO)
    service, store, client = build_service()
    collector, judge, records = make_collector(), DeepEvalJudge(), []
    print(f"student: Alyssa Gomez  SID4={SID4}  judge=local Ollama model via DeepEval GEval")
    print(f"cleared {store.clear()} cached answers so that every question takes the full Kafka pipeline")
    for question in QUESTIONS:
        result = service.ask(question)
        if result.is_cached:
            print(f"SKIP (served from cache, no Kafka path to evaluate): {question}")
            continue
        rec = evaluate_trace(result.trace_id, collector.wait(result.trace_id, 30), judge)
        rec["question"] = question
        records.append(rec)
        s, imp = rec["scores"], rec["improvement"] or {}
        print(f"\n{question}\n  trace_id={rec['trace_id']}  status={rec['status']}  evaluation took {rec['duration_s']} s")
        print(f"  plan {fmt(s['plan_quality']['score'])} | writer {fmt(s['writer_helpfulness']['score'])} | final {fmt(s['final_helpfulness']['score'])} "
              f"| draft(final metric) {fmt(s['draft_under_final_metric']['score'])} | difference {imp.get('difference', 'n/a')}")
        print(f"  {imp.get('interpretation', 'improvement not computed: ' + '; '.join(rec['problems'] + rec['errors']))}")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "evaluation_results.json").write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    print(f"\nsaved {len(records)} evaluations to reports/hw10/raw/evaluation_results.json")
    collector.close()
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())