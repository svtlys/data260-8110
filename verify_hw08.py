import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))
os.environ.setdefault("LLM_MODE", "stub")

from agent_core import SimulatedCrash, run_agent  # noqa: E402
from client import build_request, make_client  # noqa: E402
from kafka_config import (DOMAIN_ID, MAX_RETRIES, PORT_BASE, PREFIX, SEED, SID4, TOPIC_DRAFTS, TOPIC_FINAL, TOPIC_INBOX,  # noqa: E402
                          TOPIC_PARTITIONS, TOPIC_TASKS, VERIFY_SEED)
from kafka_io import KafkaConsumer, KafkaProducer, collect, ensure_topics, partition_counts  # noqa: E402
import failure_tests as ft  # noqa: E402
from planner import make_plan  # noqa: E402
from reviewer import review  # noqa: E402
from writer import make_draft  # noqa: E402

GOOD = {"address": "500 Verify Ave, San Jose, CA", "available_units": 2, "landlord_name": "Verify LLC"}
RESULTS: list = []


def code_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "code").glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def check(name: str, fn) -> None:
    started = time.time()
    try:
        ok, detail = fn()
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    RESULTS.append({"name": name, "passed": bool(ok), "detail": detail, "seconds": round(time.time() - started, 1)})
    print(("PASS  " if ok else "FAIL  ") + name + " - " + str(detail), flush=True)


def c_topics():
    counts = partition_counts()
    want = {TOPIC_INBOX: 1, TOPIC_TASKS: 2, TOPIC_DRAFTS: 1, TOPIC_FINAL: 1}
    bad = {t: counts.get(t) for t, n in want.items() if counts.get(t) != n}
    return not bad, f"partitions {({t: counts.get(t) for t in want})}" if not bad else f"wrong/missing {bad}"


def c_roundtrip():
    client = make_client()
    created = client.request(build_request("CREATE_LISTING", GOOD), timeout=20)
    got = client.request(build_request("GET_LISTING", {"listing_id": created.get("listing_id")}), timeout=20)
    client.stop()
    ok = created["success"] and got["success"] and got["listing"]["address"] == GOOD["address"]
    return ok, f"created {created.get('listing_id')} and read it back"


def c_errors():
    client = make_client()
    reqs = [build_request("GET_LISTING", {"listing_id": "missing"}), build_request("FLY_LISTING", {}), build_request("CREATE_LISTING", {"address": ""})]
    resps = [client.request(r, timeout=20) for r in reqs]
    client.stop()
    ok = all(r["success"] is False and r.get("error") and r["correlation_id"] == q["correlation_id"] for r, q in zip(resps, reqs))
    return ok, "not-found, unknown operation and invalid data all fail cleanly with the original correlation_id"


def start_stage(name, in_topic, out_topic, transform, cid, stops):
    consumer = KafkaConsumer(f"{PREFIX}_verify_{name}_{uuid.uuid4().hex[:6]}", [in_topic], client_id=f"verify-{name}")
    producer, stop = KafkaProducer(client_id=name), threading.Event()

    def target():
        try:
            run_agent(name, consumer, producer, out_topic, transform, stop, accept=lambda b: b.get("correlation_id") == cid, backoff=0.2)
        except SimulatedCrash:
            pass

    threading.Thread(target=target, daemon=True).start()
    consumer.ready.wait(30)
    stops.append((stop, consumer))


def c_pipeline():
    cid, stops = f"verify-{uuid.uuid4().hex[:8]}", []
    for name, i, o, fn in (("planner", TOPIC_INBOX, TOPIC_TASKS, make_plan), ("writer", TOPIC_TASKS, TOPIC_DRAFTS, make_draft),
                           ("reviewer", TOPIC_DRAFTS, TOPIC_FINAL, review)):
        start_stage(name, i, o, fn, cid, stops)
    KafkaProducer().send(TOPIC_INBOX, {"correlation_id": cid, "question": "What should I check before signing a lease?"}, key=cid)
    final = collect(TOPIC_FINAL, lambda b: b.get("correlation_id") == cid, lambda f: len(f) >= 1, 60)
    for stop, consumer in stops:
        stop.set()
        consumer.close()
    ok = bool(final) and final[0].get("status") == "approved" and bool(final[0].get("answer"))
    return ok, f"inbox->tasks->drafts->final, status={final[0].get('status') if final else None}, correlation_id preserved={bool(final)}"


def c_duplicate():
    r = ft.scenario_duplicate(True)
    return r["times_work_done"] == 1 and r["drafts_on_topic"] == 1, f"sent 2x, work done {r['times_work_done']}x, drafts {r['drafts_on_topic']}"


def c_poison():
    r = ft.scenario_poison(True)
    ok = r["dead_letter_messages"] == 1 and r["dead_letter_attempts"] == MAX_RETRIES and r["good_processed"] == 2
    return ok, f"attempts={r['dead_letter_attempts']}, dead-lettered={r['dead_letter_messages']}, later messages processed={r['good_processed']}/2"


def c_ordering():
    r = ft.scenario_ordering(True)
    ok = r["processed"] == 20 and r["all_entities_in_one_partition"] and r["all_entities_in_order"]
    return ok, f"processed={r['processed']}/20 one-partition-per-entity={r['all_entities_in_one_partition']} in-order={r['all_entities_in_order']}"


def c_crash():
    r = ft.scenario_crash(False)
    ok = r["exit_code_run1"] not in (0, None) and r["draft_after_restart"] == 1 and r["committed_after_restart"] == r["message_offset"] + 1
    return ok, f"exit={r['exit_code_run1']} committed_after_crash={r['committed_after_crash']} draft_after_restart={r['draft_after_restart']} committed_after_restart={r['committed_after_restart']}"


def git_hash() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> int:
    before = code_hash()
    ensure_topics(TOPIC_PARTITIONS)
    for name, fn in (("topics exist with required partitions", c_topics), ("CREATE_LISTING then GET_LISTING round-trip through Kafka", c_roundtrip),
                     ("error responses keep correlation_id", c_errors), ("three-agent pipeline inbox->final", c_pipeline),
                     ("duplicate delivery has no extra side effect (idempotency)", c_duplicate),
                     ("poison message: bounded retries then dead-letter, later messages flow", c_poison),
                     ("keyed ordering: related messages in one partition, in order", c_ordering),
                     ("writer killed mid-work: redelivered after restart, offset committed after success", c_crash)):
        check(name, fn)
    check("application code unchanged by this script", lambda: (code_hash() == before, "sha256 of code/*.py identical before and after"))
    failed = [r for r in RESULTS if not r["passed"]]
    report = {"homework": 8, "sid4": SID4, "commit_hash": git_hash(), "model_config": {"model": "qwen3:8b (Ollama)", "verify_run_llm_mode": os.environ["LLM_MODE"],
              "kafka": "apache/kafka:3.9.0 single broker", "port_base": PORT_BASE, "prefix": PREFIX, "domain_id": DOMAIN_ID},
              "seed": SEED, "verify_seed": VERIFY_SEED, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "total_checks": len(RESULTS), "passed": len(RESULTS) - len(failed), "failed": len(failed), "checks": RESULTS}
    out = ROOT / "reports" / "hw08" / "verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{report['passed']}/{report['total_checks']} checks passed -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())