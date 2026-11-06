"""
run_sweep.py - HW9 Part 3.1-3.2/3.4: threshold sweep over the 40 labeled cases in cache_cases.yaml (Alyssa Gomez, SID4 8110).

1. Seed the cache with the 10 seed queries (answered ONCE by the real HW8 pipeline; saved in raw/seed_answers.json so reruns are free).
2. For each of the 40 cases, find the nearest cached query in Redis (timed). The nearest neighbour does not depend on the threshold,
   so one lookup per case is enough to evaluate all five thresholds.
3. hit = similarity >= threshold. false hit = a hit whose matched seed has a different answer_key than the case.
   hit rate = hits/40, false-hit rate = false hits/40, mean latency = hit: measured lookup time; miss: lookup time + the mean
   MEASURED pipeline latency of Part 2 (raw/part2_results.json), because running 40 x 5 live agent calls would add nothing new.
Run:  python run_sweep.py        -> reports/hw09/raw/sweep_cases.csv, sweep_table.json, seed_answers.json
"""

import csv
import json
import logging
import sys
import time
from pathlib import Path

import redis
import yaml

from agent_adapter import PipelineClient
from cache_config import REDIS_URL, SID4, setup_logging
from cost_model import C_FALSE_HIT, C_HIT, C_MISS, choose_threshold, sensitivity, total_cost
from embedder import Embedder
from listing_records import RecordRepo, extract_listing_code, record_context, record_version
from vector_store import RedisVectorStore

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "reports" / "hw09" / "raw"
THRESHOLDS = [0.75, 0.80, 0.85, 0.90, 0.95]
log = logging.getLogger("sweep")


def seed_answers(seeds: list, repo, agent) -> dict:
    """Run each seed through the HW8 pipeline once (resumable)."""
    path = RAW / "seed_answers.json"
    done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for seed in seeds:
        if seed["id"] in done:
            continue
        rec = repo.get_by_code(extract_listing_code(seed["query"]))
        answer, ok = agent(seed["query"], record_context(rec) if rec else None)
        if not ok or not answer:
            raise RuntimeError(f"pipeline did not approve an answer for {seed['id']}")
        done[seed["id"]] = {"query": seed["query"], "answer": answer, "record_id": rec["listing_code"], "data_version": record_version(rec)}
        RAW.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(done, indent=2), encoding="utf-8")
        log.info("seed %s answered: %s", seed["id"], answer)
    return done


def nearest_for_cases(cases: list, store, embedder, seed_by_query: dict) -> list:
    rows = []
    for case in cases:
        t = time.perf_counter()
        best = store.nearest(embedder.embed(case["query"]))
        lookup_ms = (time.perf_counter() - t) * 1000.0
        seed = seed_by_query[best["query"]]
        rows.append({"id": case["id"], "category": case["category"], "query": case["query"], "expected": case["expected"],
                     "answer_key": case["answer_key"], "best_seed": seed["id"], "best_query": best["query"],
                     "best_answer_key": seed["answer_key"], "similarity": round(best["similarity"], 4), "lookup_ms": round(lookup_ms, 2)})
    return rows


def evaluate(rows: list, miss_ms: float) -> list:
    table = []
    for t in THRESHOLDS:
        hits = [r for r in rows if r["similarity"] >= t]
        false_hits = [r for r in hits if r["best_answer_key"] != r["answer_key"]]
        lat = [r["lookup_ms"] if r["similarity"] >= t else r["lookup_ms"] + miss_ms for r in rows]
        n = len(rows)
        table.append({"threshold": t, "hits": len(hits), "false_hits": len(false_hits), "misses": n - len(hits),
                      "hit_rate_pct": round(100 * len(hits) / n, 1), "false_hit_rate_pct": round(100 * len(false_hits) / n, 1),
                      "mean_latency_ms": round(sum(lat) / n, 1), "total_cost": total_cost(len(hits), len(false_hits), n - len(hits)),
                      "false_hit_ids": [r["id"] for r in false_hits]})
    return table


def main() -> int:
    setup_logging(logging.INFO)
    from db import db_session_basede26

    spec = yaml.safe_load((HERE / "cache_cases.yaml").read_text(encoding="utf-8"))
    part2 = RAW / "part2_results.json"
    if not part2.exists():
        print("run python run_part2.py first: the sweep needs the measured pipeline latency from it")
        return 1
    miss_ms = json.loads(part2.read_text())["summary"]["avg_latency_not_cached_ms"]
    repo, embedder = RecordRepo(db_session_basede26), Embedder()
    agent = PipelineClient()
    answers = seed_answers(spec["seeds"], repo, agent)
    store = RedisVectorStore(redis.Redis.from_url(REDIS_URL, decode_responses=False))
    store.clear()
    for seed in spec["seeds"]:
        a = answers[seed["id"]]
        store.add(a["query"], a["answer"], embedder.embed(a["query"]), a["record_id"], a["data_version"])
    rows = nearest_for_cases(spec["cases"], store, embedder, {s["query"]: s for s in spec["seeds"]})
    table = evaluate(rows, miss_ms)
    RAW.mkdir(parents=True, exist_ok=True)
    with open(RAW / "sweep_cases.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    best = choose_threshold(table)
    out = {"student": "Alyssa Gomez", "sid4": SID4, "miss_latency_ms_from_part2": miss_ms, "costs": {"c_miss": C_MISS, "c_hit": C_HIT, "c_false_hit": C_FALSE_HIT},
           "table": table, "chosen_threshold": best["threshold"], "sensitivity": sensitivity(table)}
    (RAW / "sweep_table.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nstudent: Alyssa Gomez  SID4={SID4}  (miss latency used: {miss_ms} ms, measured in Part 2)")
    print("Threshold | Hit rate | False-hit rate | Mean latency (ms) | Total cost ($) | false-hit cases")
    for r in table:
        print(f"{r['threshold']:<9} | {r['hit_rate_pct']:>6}% | {r['false_hit_rate_pct']:>13}% | {r['mean_latency_ms']:>17} | {r['total_cost']:>14} | {','.join(r['false_hit_ids']) or '-'}")
    print(f"\ncheapest threshold: {best['threshold']}  | sensitivity to false-hit cost: {out['sensitivity']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())