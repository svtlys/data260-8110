import sys
import time

from judge import JUDGE_MODEL, DeepEvalJudge

Q = "How many units are available at listing S8110-A01?"
FACTS = ["listing S8110-A01: address 450 Maple Ave, San Jose; available_units 3; landlord Bayview Rentals"]


def main() -> int:
    print(f"student: Alyssa Gomez  SID4=8110  judge model: {JUDGE_MODEL}")
    judge, start = DeepEvalJudge(), time.time()
    good = judge.score("final_helpfulness", Q, "There are 3 units available at listing S8110-A01.", FACTS)
    bad = judge.score("final_helpfulness", Q, "The weather in San Jose is usually sunny in the summer.", FACTS)
    print(f"good answer : {good.score}  ({good.reason[:110]})")
    print(f"bad answer  : {bad.score}  ({bad.reason[:110]})")
    ok = good.score > bad.score
    print(f"{'PASS' if ok else 'FAIL'}: good > bad, 2 judge calls in {time.time() - start:.1f} s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())