import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODE, DATA, RAW = ROOT / "code", ROOT / "data" / "hw09", ROOT / "reports" / "hw09" / "raw"
sys.path.insert(0, str(CODE))

from cache_config import DOMAIN_ID, PORT_BASE, PREFIX, REDIS_URL, SEED, SID4, SYNC_EVERY, VERIFY_SEED  # noqa: E402
from cost_model import choose_threshold  # noqa: E402

RESULTS: list = []
THRESHOLDS = [0.75, 0.8, 0.85, 0.9, 0.95]
SPLIT_KEYS = {"id", "listing_id", "question"}
LESSON_KEYS = {"lesson_id", "failure_pattern", "correction", "created_at", "use_count"}
VARIANTS = ["Baseline", "Evaluator Repair", "Lesson Memory", "Validated Improvement"]


class Skip(Exception):
    """Raised by a check that cannot run in this environment."""


def code_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(CODE.glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def check(name: str, fn) -> None:
    started = time.time()
    try:
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
    except Skip as exc:
        status, detail = "SKIP", str(exc)
    except Exception as exc:  # a crashing check is a failed check
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    RESULTS.append({"name": name, "status": status, "detail": detail, "seconds": round(time.time() - started, 1)})
    print(f"{status:<5} {name} - {detail}", flush=True)


def jload(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"missing {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def redis_client():
    try:
        import redis
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        raise Skip(f"Redis not reachable ({type(exc).__name__})") from exc


# ---------------- Section 0 / unit tests ----------------
def c_section0():
    want = {"SID4": "8110", "PORT_BASE": 8010, "PREFIX": "s8110", "SEED": 8110, "VERIFY_SEED": 268110, "DOMAIN_ID": 6}
    got = {"SID4": SID4, "PORT_BASE": PORT_BASE, "PREFIX": PREFIX, "SEED": SEED, "VERIFY_SEED": VERIFY_SEED, "DOMAIN_ID": DOMAIN_ID}
    return got == want, f"{got}"


def c_unit_tests():
    files = ["test_hw9_part1.py", "test_hw9_part2.py", "test_hw9_part4.py"]
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], cwd=CODE, capture_output=True, text=True, timeout=300)
    lines = (proc.stdout.strip() or proc.stderr.strip()).splitlines()
    last = lines[-1] if lines else "no output"
    return proc.returncode == 0, f"offline tests (Parts 1, 2, 4): {last}"


# ---------------- Part 1 (live Redis) ----------------
def c_part1_counter():
    from listing_cache import ListingCache

    class Repo:
        def __init__(self):
            self.saved = []

        def save_views(self, listing_id, count):
            self.saved.append((listing_id, count))
            return True

    client, repo, lid = redis_client(), Repo(), f"verify{VERIFY_SEED}"
    cache = ListingCache(client, repo)
    client.delete(cache.views_key(lid))
    try:
        counts = [cache.increment_listing_views(lid) for _ in range(25)]
    finally:
        client.delete(cache.views_key(lid))
    ok = counts == list(range(1, 26)) and repo.saved == [(lid, SYNC_EVERY), (lid, 2 * SYNC_EVERY)]
    return ok, f"25 increments returned 1..25; database synced at {[c for _, c in repo.saved]} (every {SYNC_EVERY})"


def c_redis_prefix():
    client = redis_client()
    keys = list(client.scan_iter("*", count=500))
    bad = [k for k in keys if not k.startswith(PREFIX + ":")]
    return not bad, f"{len(keys)} keys in Redis, all start with '{PREFIX}:'" if not bad else f"keys without prefix: {bad[:5]}"


def c_vector_index():
    client = redis_client()
    from vector_store import INDEX

    info = client.execute_command("FT.INFO", INDEX)
    return bool(info), f"RediSearch index {INDEX} exists"


# ---------------- Part 2 ----------------
def c_part2():
    data = jload(RAW / "part2_results.json")
    rows, s = data["queries"], data["summary"]
    kinds = {r["kind"] for r in rows}
    hits = sum(1 for r in rows if r["is_cached"])
    ok = (len(rows) >= 10 and {"exact duplicate", "paraphrase", "new"} <= kinds and s["queries"] == len(rows) and s["hits"] == hits
          and abs(s["hit_rate_pct"] - round(100 * hits / len(rows), 1)) < 0.11
          and all(set(r) >= {"is_cached", "similarity", "latency_ms"} for r in rows) and data["threshold"] == 0.85)
    return ok, (f"{len(rows)} queries, kinds={sorted(kinds)}, hit rate {s['hit_rate_pct']}%, avg cached {s['avg_latency_cached_ms']} ms "
                f"vs not cached {s['avg_latency_not_cached_ms']} ms")


# ---------------- Part 3 ----------------
def c_cases_file():
    import yaml

    spec = yaml.safe_load((CODE / "cache_cases.yaml").read_text(encoding="utf-8"))
    cases = spec["cases"]
    labeled = all(c.get("answer_key") and c.get("expected") in ("hit", "miss") for c in cases)
    return len(cases) == 40 and len(spec["seeds"]) == 10 and labeled, f"{len(cases)} labeled cases, {len(spec['seeds'])} seeds"


def c_cases_committed_first():
    log = subprocess.run(["git", "log", "--format=%ct", "--", ":(glob)**/cache_cases.yaml"], cwd=ROOT, capture_output=True, text=True)
    stamps = [int(x) for x in log.stdout.split()]
    if log.returncode != 0:
        raise Skip("git not available")
    if not stamps:
        return False, "cache_cases.yaml is not committed yet"
    first_commit, produced = min(stamps), (RAW / "sweep_table.json").stat().st_mtime
    when = datetime.fromtimestamp(first_commit, timezone.utc).isoformat(timespec="seconds")
    return first_commit <= produced, f"cache_cases.yaml first committed {when}, sweep result written {datetime.fromtimestamp(produced, timezone.utc).isoformat(timespec='seconds')}"


def c_sweep():
    data = jload(RAW / "sweep_table.json")
    table = data["table"]
    rows = list(csv.DictReader(open(RAW / "sweep_cases.csv", encoding="utf-8")))
    thresholds = [r["threshold"] for r in table]
    recomputed = choose_threshold([{k: r[k] for k in ("threshold", "hits", "false_hits", "misses")} for r in table])["threshold"]
    consistent = all(r["hits"] + r["misses"] == len(rows) and r["false_hits"] <= r["hits"] for r in table)
    ok = thresholds == THRESHOLDS and len(rows) == 40 and consistent and recomputed == data["chosen_threshold"]
    return ok, f"thresholds {thresholds}, {len(rows)} cases, chosen threshold {data['chosen_threshold']} (recomputed {recomputed})"


def c_stale():
    steps = jload(RAW / "stale_demo.json")
    first, stale, fixed, again = steps
    ok = (not first["is_cached"] and stale["is_cached"] and stale["answer"] != fixed["answer"] and fixed["stale_invalidated"]
          and not fixed["is_cached"] and again["is_cached"] and again["answer"] == fixed["answer"])
    return ok, "stale hit served before invalidation; data-version check dropped it, re-ran the agent, then the fresh answer was cached"


# ---------------- Part 4 ----------------
def c_datasets():
    splits = {n: jload(DATA / f"{n}_data.json") for n in ("training", "validation", "test")}
    ref = jload(DATA / "reference_dataset.json")
    pairs = {n: {(i["listing_id"], i["question"]) for i in items} for n, items in splits.items()}
    ids = [i["id"] for items in splits.values() for i in items]
    clean = all(set(i) == SPLIT_KEYS for items in splits.values() for i in items)
    disjoint = not (pairs["training"] & pairs["validation"] or pairs["training"] & pairs["test"] or pairs["validation"] & pairs["test"])
    known = all(i["listing_id"] in ref for items in splits.values() for i in items)
    ok = clean and disjoint and known and len(ids) == len(set(ids)) and [len(v) for v in splits.values()] == [12, 12, 20]
    return ok, f"train/validation/test = {[len(v) for v in splits.values()]}, questions only (no answer fields), no overlap, all listings in reference dataset"


def c_lessons():
    lessons, cands = jload(DATA / "lessons.json"), jload(DATA / "lessons_candidates.json")
    report = {r["lesson_id"]: r for r in jload(RAW / "validation_report.json")["lessons"]}
    cand_ids = {c["lesson_id"] for c in cands}
    fields = all(LESSON_KEYS <= set(le) for le in lessons)
    validated = all(report[le["lesson_id"]]["keep"] for le in lessons)
    no_test = all(not str(e).startswith("te") for le in cands for e in le.get("evidence_ids", []))
    removed_ok = all(not r["keep"] for lid, r in report.items() if lid not in {le["lesson_id"] for le in lessons})
    ok = fields and validated and no_test and removed_ok and {le["lesson_id"] for le in lessons} <= cand_ids
    return ok, f"{len(lessons)} kept of {len(cands)} candidates; every kept lesson passed validation; no lesson built from test questions"


def c_variants():
    data = jload(RAW / "variant_results.json")
    table = {r["variant"]: r for r in data["table"]}
    detail = data["detail"]
    sizes_ok = all(r["correct"] + r["incorrect"] == 20 for r in table.values())
    attempts_ok = all(x["n_attempts"] <= 2 for v in detail.values() for x in v["results"])
    base_one = all(x["n_attempts"] == 1 for x in detail["Baseline"]["results"])
    ok = list(table) == VARIANTS and sizes_ok and attempts_ok and base_one
    row = "; ".join(f"{n}: {r['correct']}/20, {r['avg_attempts']} attempts, {r['avg_latency_s']} s" for n, r in table.items())
    return ok, row


def c_demo():
    demo = jload(RAW / "part4_demo.json")
    ctrl, reuse = demo["controlled_revision"], demo["lesson_reuse"]["with_lessons"]
    seq = [a["verdict"] for a in ctrl["attempts"]]
    ok = seq == ["REVISE", "PASS"] and ctrl["n_attempts"] <= 2 and ctrl["correct"] and bool(reuse["lessons_used"])
    return ok, f"controlled case {seq} in {ctrl['n_attempts']} attempts; lessons reused: {reuse['lessons_used']}"


def c_max_attempts():
    over = [x["id"] for v in jload(RAW / "variant_results.json")["detail"].values() for x in v["results"] if x["n_attempts"] > 2]
    return not over, "no question used more than 2 attempts (stopping condition)" if not over else f"over limit: {over}"


def main() -> int:
    before = code_hash()
    print(f"HW9 verification - Alyssa Gomez, SID4={SID4}, PREFIX={PREFIX}\n")
    for name, fn in (("section 0 values", c_section0), ("offline unit tests", c_unit_tests),
                     ("part 1: live counter + sync every 10", c_part1_counter), ("part 1: every Redis key starts with PREFIX", c_redis_prefix),
                     ("part 2: vector index exists", c_vector_index), ("part 2: semantic cache results", c_part2),
                     ("part 3.1: 40 labeled cases", c_cases_file), ("part 3.1: cases committed before sweep", c_cases_committed_first),
                     ("part 3.2/3.4: threshold sweep + chosen threshold", c_sweep), ("part 3.5: stale answer + invalidation", c_stale),
                     ("part 4: datasets", c_datasets), ("part 4.2/4.3: lessons validated", c_lessons),
                     ("part 4.4: four variants", c_variants), ("part 4.1/4.2: demos", c_demo), ("part 4.1: stopping condition", c_max_attempts)):
        check(name, fn)
    after = code_hash()
    check("application code unchanged by verification", lambda: (before == after, f"sha256 {after[:16]}..."))
    counts = {s: sum(r["status"] == s for r in RESULTS) for s in ("PASS", "FAIL", "SKIP")}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    out = {"student": "Alyssa Gomez", "sid4": SID4, "prefix": PREFIX, "seed": SEED, "verify_seed": VERIFY_SEED, "git_commit": commit,
           "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code_sha256": after, "summary": counts, "checks": RESULTS}
    path = ROOT / "reports" / "hw09" / "verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped -> {path.relative_to(ROOT)}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())