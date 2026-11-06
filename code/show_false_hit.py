import csv
import json
import re
import sys
from pathlib import Path

from listing_records import RecordRepo, extract_listing_code, ground_truth

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw09" / "raw"


def tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9\-]+", text.lower()))


def main() -> int:
    from db import db_session_basede26

    threshold = float(sys.argv[1]) if len(sys.argv) > 1 else 0.85
    rows = list(csv.DictReader(open(RAW / "sweep_cases.csv", encoding="utf-8")))
    answers = json.loads((RAW / "seed_answers.json").read_text(encoding="utf-8"))
    false = [r for r in rows if r["best_answer_key"] != r["answer_key"] and float(r["similarity"]) >= threshold]
    note = ""
    if not false:
        false = [r for r in rows if r["best_answer_key"] != r["answer_key"]]
        note = f"(no false hit at threshold {threshold}; showing the highest-similarity wrong match, which WOULD hit at a lower threshold)"
    r = max(false, key=lambda x: float(x["similarity"]))
    repo = RecordRepo(db_session_basede26)
    rec = repo.get_by_code(extract_listing_code(r["query"]))
    print(f"=== FALSE HIT {note}===")
    print(f"case {r['id']} ({r['category']})")
    print(f"cached query   : {r['best_query']}")
    print(f"incoming query : {r['query']}")
    print(f"similarity     : {r['similarity']}  (threshold {threshold})")
    print(f"cached answer returned : {answers[r['best_seed']]['answer']}")
    print(f"correct answer (from database): {ground_truth(r['query'], rec)}")
    a, b = tokens(r["best_query"]), tokens(r["query"])
    print(f"shared words   : {sorted(a & b)}")
    print(f"different words: cached only {sorted(a - b)} | incoming only {sorted(b - a)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())