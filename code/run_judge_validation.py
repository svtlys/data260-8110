import csv
import json
import subprocess
import sys
import time
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, RAW = ROOT / "data" / "hw10", ROOT / "reports" / "hw10" / "raw"
CSV_PATH, JSON_PATH = RAW / "judge_validation_cases.csv", RAW / "judge_validation.json"
RUNS, METRIC, MAX_ERRORS = 3, "writer_helpfulness", 3


def round_half_up(x: float) -> int:
    return int(x + 0.5)


def mean(xs: list) -> float:
    return sum(xs) / len(xs)


def agreement(human: list, judge: list) -> dict:
    """Spearman rank correlation and mean absolute difference between two score lists."""
    from scipy.stats import spearmanr

    rho, p = spearmanr(human, judge)
    ok = rho == rho  # NaN when one list is constant
    return {"spearman_rho": round(float(rho), 4) if ok else None, "spearman_p": round(float(p), 4) if ok else None,
            "mean_abs_difference": round(mean([abs(j - h) for h, j in zip(human, judge)]), 4),
            "mean_signed_difference_judge_minus_human": round(mean([j - h for h, j in zip(human, judge)]), 4)}


def repeatability(runs_by_case: list, rounded: bool = False) -> dict:
    """How often and how much scores change between repeated runs of the same inputs. runs_by_case: [[run1, run2, run3], ...]."""
    scores = [[round_half_up(x) if rounded else x for x in case] for case in runs_by_case]
    changes = [abs(a - b) for case in scores for a, b in combinations(case, 2)]
    changed_cases = sum(1 for case in scores if max(case) != min(case))
    return {"runs": len(scores[0]), "cases_with_any_change": changed_cases, "pct_cases_with_any_change": round(100.0 * changed_cases / len(scores), 1),
            "pairwise_comparisons": len(changes), "pairs_that_differ": sum(1 for c in changes if c > 0),
            "mean_abs_change": round(mean(changes), 4), "max_abs_change": round(max(changes), 4)}


def compute_stats(rows: list) -> dict:
    """rows: [{'human': int, 'runs': [float, ...]}] (cases with every run scored). Everything reported is computed here from the raw rows."""
    human, runs = [r["human"] for r in rows], [r["runs"] for r in rows]
    first, avg = [r[0] for r in runs], [mean(r) for r in runs]
    return {"n_cases": len(rows),
            "agreement_run1": agreement(human, first),
            "agreement_run1_rounded_to_integers": agreement(human, [round_half_up(x) for x in first]),
            "agreement_mean_of_runs": agreement(human, avg),
            "repeatability": repeatability(runs), "repeatability_rounded_to_integers": repeatability(runs, rounded=True)}


def read_cases_csv(path: Path) -> list:
    """Raw per-case CSV -> rows for compute_stats (cases with a missing score are left out)."""
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        for rec in csv.DictReader(handle):
            runs = [rec[f"judge_run{i}"] for i in range(1, RUNS + 1)]
            if all(x != "" for x in runs):
                rows.append({"case_id": rec["case_id"], "human": int(rec["human_label"]), "runs": [float(x) for x in runs]})
    return rows


def labels_ready() -> tuple:
    """(ok, message): labels complete, committed, and not modified since the commit."""
    from label_cases import load_labels

    labels = load_labels(DATA / "human_labels.csv")
    if any(v is None for v in labels.values()) or len(labels) != 20:
        return False, "human_labels.csv is not complete (python label_cases.py --check)"
    rel = "data/hw10"
    stamps = subprocess.run(["git", "log", "--format=%ct", "--", f"{rel}/human_labels.csv", f"{rel}/eval_cases.json"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if not stamps:
        return False, "eval_cases.json / human_labels.csv are not committed yet - commit them before running the judge"
    if dirty:
        return False, f"uncommitted changes in data/hw10:\n{dirty}"
    return True, f"labels committed at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max(int(s) for s in stamps)))}"


def judge_all(cases: list, labels: dict) -> list:
    """3 runs x 20 cases. Returns raw rows (None for a failed call). Aborts when the judge is unavailable or errors repeat."""
    from judge import DeepEvalJudge, JudgeUnavailable

    judge, rows, errors = DeepEvalJudge(), [{"case_id": c["case_id"], "variant": c["variant"], "human_label": labels[c["case_id"]], "runs": [], "reasons": []} for c in cases], 0
    for run in range(1, RUNS + 1):
        for case, row in zip(cases, rows):
            try:
                res = judge.score(METRIC, case["question"], case["draft"], case["context"])
                row["runs"].append(res.score)
                row["reasons"].append(res.reason)
                print(f"run {run}/{RUNS} {case['case_id']:<5} judge={res.score:<5} human={row['human_label']}", flush=True)
            except JudgeUnavailable as exc:
                raise SystemExit(f"judge unavailable - stopping: {exc}") from exc
            except Exception as exc:
                errors += 1
                row["runs"].append(None)
                row["reasons"].append(f"ERROR {type(exc).__name__}: {exc}")
                print(f"run {run}/{RUNS} {case['case_id']} ERROR {exc}", flush=True)
                if errors >= MAX_ERRORS:
                    raise SystemExit(f"{errors} judge errors - stopping") from exc
    return rows


def write_cases_csv(rows: list) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "variant", "human_label"] + [f"judge_run{i}" for i in range(1, RUNS + 1)] + ["reason_run1"])
        for r in rows:
            writer.writerow([r["case_id"], r["variant"], r["human_label"]] + ["" if x is None else x for x in r["runs"]] + [r["reasons"][0] if r["reasons"] else ""])


def print_stats(stats: dict) -> None:
    a, rp = stats["agreement_run1"], stats["repeatability"]
    print(f"\n=== Judge vs human labels (n={stats['n_cases']}, run 1) ===")
    print(f"Spearman rank correlation : {a['spearman_rho']}  (p={a['spearman_p']})")
    print(f"Mean absolute difference  : {a['mean_abs_difference']}  (signed judge-human: {a['mean_signed_difference_judge_minus_human']})")
    print(f"... with scores rounded to integers: rho={stats['agreement_run1_rounded_to_integers']['spearman_rho']}, MAD={stats['agreement_run1_rounded_to_integers']['mean_abs_difference']}")
    print(f"=== Repeatability ({rp['runs']} runs, same inputs and settings) ===")
    print(f"cases whose score changed : {rp['cases_with_any_change']}/{stats['n_cases']} ({rp['pct_cases_with_any_change']}%)")
    print(f"run pairs that differ     : {rp['pairs_that_differ']}/{rp['pairwise_comparisons']}")
    print(f"mean / max absolute change: {rp['mean_abs_change']} / {rp['max_abs_change']}")


def main() -> int:
    recompute = "--recompute" in sys.argv
    print("student: Alyssa Gomez  SID4=8110")
    if recompute:
        stats, note = compute_stats(read_cases_csv(CSV_PATH)), "recomputed from raw CSV"
    else:
        ok, message = labels_ready()
        print(message)
        if not ok:
            return 1
        cases = json.loads((DATA / "eval_cases.json").read_text(encoding="utf-8"))
        from judge import settings
        from label_cases import load_labels

        rows = judge_all(cases, load_labels(DATA / "human_labels.csv"))
        write_cases_csv(rows)
        stats, note = compute_stats(read_cases_csv(CSV_PATH)), message
        JSON_PATH.write_text(json.dumps({"stats": stats, "labels": note, "judge": settings(), "metric": METRIC, "ran_at": time.time()}, indent=2), encoding="utf-8")
    print_stats(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())