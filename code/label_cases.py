import csv
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "hw10"


def parse_label(text: str) -> int | None:
    """'4' -> 4; anything that is not an integer 1-5 -> None."""
    text = text.strip()
    return int(text) if text in {"1", "2", "3", "4", "5"} else None


def load_labels(path: Path) -> dict:
    """case_id -> label (int) or None for an empty cell."""
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["case_id"]: parse_label(row["human_label"]) for row in csv.DictReader(handle)}


def save_labels(path: Path, labels: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "human_label"])
        writer.writerows([[cid, "" if lab is None else lab] for cid, lab in labels.items()])


def show(case: dict, position: int, total: int) -> None:
    print(f"\n[{position}/{total}] {case['case_id']}")
    print(f"QUESTION: {case['question']}")
    if case.get("context"):
        print(f"DATABASE FACTS GIVEN TO THE WRITER: {case['context'][0]}")
    print(f"DRAFT:\n{case['draft']}\n")


def main() -> int:
    cases = json.loads((DATA / "eval_cases.json").read_text(encoding="utf-8"))
    path = DATA / "human_labels.csv"
    labels = load_labels(path)
    if "--check" in sys.argv:
        missing = [cid for cid, lab in labels.items() if lab is None]
        print(f"{len(labels) - len(missing)}/{len(labels)} labeled" + (f"; missing: {missing}" if missing else " - complete"))
        return 1 if missing else 0
    for position, case in enumerate(cases, 1):
        if labels.get(case["case_id"]) is not None:
            continue
        show(case, position, len(cases))
        while True:
            answer = input("your label (1-5, q to quit): ").strip().lower()
            if answer == "q":
                print("saved - run again to continue")
                return 0
            label = parse_label(answer)
            if label is not None:
                labels[case["case_id"]] = label
                save_labels(path, labels)
                break
            print("enter a whole number from 1 to 5")
    print("all cases labeled. Now COMMIT eval_cases.json and human_labels.csv before running any judge.")
    return 0


if __name__ == "__main__":
    sys.exit(main())