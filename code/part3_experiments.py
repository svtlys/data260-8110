import csv
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

import domain_tools5 as domain_tools  
from db import db_session_basede26  
from models import Listing  
from resilience import INTERACTIVE_POLICY, FaultInjector, ScriptedFaults 

VERIFY_SEED = 268110
FAILURE_RATES = [0.0, 0.2, 0.5]
CALLS_PER_RATE = 50
RAW_DIR = Path(__file__).resolve().parent.parent / "reports/hw05/raw"


def existing_listing_ids(n: int = 25) -> list[int]:
    """Listing ids that really exist, so 'not found' never pollutes the results."""
    session = db_session_basede26()
    try:
        return [row[0] for row in session.query(Listing.id).order_by(Listing.id).limit(n).all()]
    finally:
        session.close()


def percentile(values, p):
    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    lower = int(k)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (k - lower)


def demo():
    listing_id = existing_listing_ids(1)[0]
    scenarios = [
        ("A: success on the first attempt", ScriptedFaults([])),
        ("B: first attempt fails, succeeds after one retry", ScriptedFaults([True])),
        ("C: every attempt fails (retries exhausted)", ScriptedFaults([True] * 10)),
    ]
    domain_tools.set_retry_policy(INTERACTIVE_POLICY)
    record = []
    for label, faults in scenarios:
        domain_tools.set_fault_hook(faults)
        print(f"\n=== Scenario {label} ===", flush=True)
        started = time.perf_counter()
        envelope = domain_tools.get_listing_detail(listing_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"attempts: {faults.attempts}   elapsed: {elapsed_ms:.0f} ms")
        print(json.dumps(envelope, indent=2))
        record.append({"scenario": label, "attempts": faults.attempts,
                       "elapsed_ms": round(elapsed_ms, 1), "envelope": envelope})
    domain_tools.set_fault_hook(None)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "retry_demo.json").write_text(json.dumps(record, indent=2))
    print(f"\nSaved {RAW_DIR / 'retry_demo.json'}")


def inject():
    ids = existing_listing_ids(25)
    domain_tools.set_retry_policy(INTERACTIVE_POLICY)
    rows = []
    for rate in FAILURE_RATES:
        injector = FaultInjector(rate, VERIFY_SEED)  # fresh generator, same seed, for every rate
        domain_tools.set_fault_hook(injector)
        print(f"running {CALLS_PER_RATE} calls at {rate:.0%} injected failures ...", flush=True)
        for i in range(CALLS_PER_RATE):
            before = injector.attempts
            started = time.perf_counter()
            envelope = domain_tools.get_listing_detail(ids[i % len(ids)])
            latency_ms = (time.perf_counter() - started) * 1000
            rows.append({
                "failure_rate": rate,
                "call": i + 1,
                "ok": envelope["ok"],
                "attempts": injector.attempts - before,
                "latency_ms": round(latency_ms, 2),
                "error": envelope["error"],
            })
    domain_tools.set_fault_hook(None)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "fault_injection_results.json").write_text(json.dumps(rows, indent=2))
    with open(RAW_DIR / "fault_injection_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    sequence = "|".join(f"{r['failure_rate']}:{r['call']}:{r['ok']}:{r['attempts']}" for r in rows)
    fingerprint = hashlib.sha256(sequence.encode()).hexdigest()[:16]

    summary = []
    print("\nInjected failure rate | Success rate | Mean latency (ms) | p99 latency (ms) | Mean attempts")
    for rate in FAILURE_RATES:
        subset = [r for r in rows if r["failure_rate"] == rate]
        latencies = [r["latency_ms"] for r in subset]
        entry = {
            "failure_rate": rate,
            "calls": len(subset),
            "success_rate": sum(1 for r in subset if r["ok"]) / len(subset),
            "mean_latency_ms": round(sum(latencies) / len(latencies), 2),
            "p99_latency_ms": round(percentile(latencies, 99), 2),
            "mean_attempts": round(sum(r["attempts"] for r in subset) / len(subset), 2),
        }
        summary.append(entry)
        print(f"{rate:>20.0%} | {entry['success_rate']:>11.0%} | {entry['mean_latency_ms']:>17.2f} | "
              f"{entry['p99_latency_ms']:>16.2f} | {entry['mean_attempts']:>13.2f}")

    (RAW_DIR / "fault_injection_summary.json").write_text(json.dumps({
        "verify_seed": VERIFY_SEED,
        "policy": vars(INTERACTIVE_POLICY),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcome_fingerprint": fingerprint,
        "summary": summary,
    }, indent=2))
    print(f"\nOutcome fingerprint (same on every run with seed {VERIFY_SEED}): {fingerprint}")
    print(f"Saved 150 raw rows and summary to {RAW_DIR}")


if __name__ == "__main__":
    commands = {"demo": demo, "inject": inject}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit("usage: python part3_experiments.py [demo|inject]")
    commands[sys.argv[1]]()