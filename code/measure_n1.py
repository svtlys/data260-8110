import csv
import json
import time
from pathlib import Path

import requests

API_BASE = "http://localhost:8010"
PAGE_SIZES = [10, 50, 200]
VERSIONS = ["naive", "fixed"]
RUNS_PER_COMBO = 30

RAW_DIR = Path(__file__).resolve().parent.parent / "reports/hw04/raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def login():
    session = requests.Session()
    resp = session.post(
        f"{API_BASE}/api/login",
        json={"email": "landlord@example.com", "password": "rentals123"},
    )
    resp.raise_for_status()
    return session


def percentile(values, p):
    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


if __name__ == "__main__":
    session = login()
    print("Logged in.")

    all_results = []

    for page_size in PAGE_SIZES:
        for version in VERSIONS:
            endpoint = f"listings-{version}"
            print(f"\n=== page_size={page_size}, version={version} ===")

            for i in range(RUNS_PER_COMBO):
                t0 = time.time()
                resp = session.get(
                    f"{API_BASE}/api/{endpoint}",
                    params={"page": 1, "page_size": page_size},
                )
                latency_ms = (time.time() - t0) * 1000
                resp.raise_for_status()
                data = resp.json()

                row = {
                    "page_size": page_size,
                    "version": version,
                    "run": i,
                    "sql_query_count": data["sql_query_count"],
                    "latency_ms": latency_ms,
                }
                all_results.append(row)
                print(f"  run {i+1}/{RUNS_PER_COMBO}: "
                      f"sql_queries={row['sql_query_count']} latency={latency_ms:.1f}ms")

    # Save raw results (180 rows total)
    json_path = RAW_DIR / "n1_measurement_results.json"
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)

    csv_path = RAW_DIR / "n1_measurement_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["page_size", "version", "run", "sql_query_count", "latency_ms"])
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\nRaw results ({len(all_results)} rows) saved to {json_path} and {csv_path}")

    # Summary table
    print("\n=== SUMMARY ===")
    print(f"{'Page':<6}{'Version':<8}{'SQL/req':<10}{'p50 (ms)':<12}{'p95 (ms)':<12}{'p99 (ms)':<12}")
    for page_size in PAGE_SIZES:
        for version in VERSIONS:
            matching = [r for r in all_results if r["page_size"] == page_size and r["version"] == version]
            latencies = [r["latency_ms"] for r in matching]
            sql_count = matching[0]["sql_query_count"]  # should be constant per combo
            p50 = percentile(latencies, 50)
            p95 = percentile(latencies, 95)
            p99 = percentile(latencies, 99)
            print(f"{page_size:<6}{version:<8}{sql_count:<10}{p50:<12.1f}{p95:<12.1f}{p99:<12.1f}")