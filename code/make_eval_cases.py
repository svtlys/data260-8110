import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "hw10"

GENERAL = ["What should I check in a lease before I sign it?", "How much security deposit can a landlord ask for in California?",
           "How do I ask my landlord to fix a leaking kitchen faucet?", "What is the difference between a lease and a month-to-month rental?",
           "Can my landlord enter my apartment without telling me?", "What fees should I expect when applying for an apartment?",
           "How do I get my deposit back when I move out?", "What questions should I ask during an apartment tour?"]
WITH_FACTS = ["How many units are available at listing S8110-A01?", "Who is the landlord for listing S8110-A02?",
              "What is the address of listing S8110-A03?", "Is listing S8110-A04 currently available?", "How many units are available at listing S8110-A06?"]
NO_FACTS = ["What is the monthly rent for listing S8110-A05?", "Does listing S8110-A07 allow pets?", "What year was the building at listing S8110-A08 built?"]
OFF_TOPIC = ["What is the best pizza place near San Jose State University?", "help"]
BAD_PLAN = [("How do I get my deposit back when I move out?", "How do I bake sourdough bread at home?"),
            ("Can my landlord enter my apartment without telling me?", "What is the capital of Australia?")]


def build_cases(plan_fn, draft_fn, context_fn, now=time.time) -> list[dict]:
    """plan_fn(question) -> steps, draft_fn(question, steps, context) -> draft text, context_fn(question) -> facts string or None."""
    specs = ([(q, "general", False, None) for q in GENERAL] + [(q, "with_database_facts", True, None) for q in WITH_FACTS]
             + [(q, "no_facts_available", False, None) for q in NO_FACTS] + [(q, "off_topic_or_vague", False, None) for q in OFF_TOPIC]
             + [(q, "mismatched_plan", False, other) for q, other in BAD_PLAN])
    cases = []
    for i, (question, variant, use_facts, plan_for) in enumerate(specs, 1):
        steps = plan_fn(plan_for or question)
        context = context_fn(question) if use_facts else None
        cases.append({"case_id": f"ec{i:02d}", "question": question, "plan": steps, "context": [context] if context else None,
                      "draft": draft_fn(question, steps, context), "variant": variant, "source": "Planner/Writer code (llm.py), local model",
                      "created_at": round(now(), 3)})
    return cases


def real_functions():
    """Real model + database wiring; never accepts the stub fallback."""
    import llm
    from db import db_session_basede26
    from listing_records import RecordRepo, extract_listing_code, record_context

    repo = RecordRepo(db_session_basede26)

    def plan_fn(question):
        steps, source = llm.plan_steps(question)
        if source == "stub":
            raise RuntimeError("Ollama is not answering (stub fallback) - start Ollama and retry")
        return steps

    def draft_fn(question, steps, context):
        draft, source = llm.write_draft(question, steps, context)
        if source == "stub":
            raise RuntimeError("Ollama is not answering (stub fallback) - start Ollama and retry")
        return draft

    def context_fn(question):
        rec = repo.get_by_code(extract_listing_code(question))
        return record_context(rec) if rec else None

    return plan_fn, draft_fn, context_fn


def main() -> int:
    if (DATA / "human_labels.csv").exists() or (DATA / "eval_cases.json").exists():
        print("eval_cases.json / human_labels.csv already exist - they are frozen. Delete them yourself only if you have not committed them.")
        return 1
    cases = build_cases(*real_functions())
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "eval_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    with open(DATA / "human_labels.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "human_label"])
        writer.writerows([[c["case_id"], ""] for c in cases])
    print(f"wrote {len(cases)} cases to data/hw10/eval_cases.json and an empty data/hw10/human_labels.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())