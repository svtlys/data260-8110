import json
import logging
import sys
from pathlib import Path

import redis

from agent_adapter import PipelineClient
from cache_config import DEFAULT_THRESHOLD, REDIS_URL, SID4, setup_logging
from embedder import Embedder
from listing_records import RecordRepo
from semantic_cache import CacheStats, SemanticCache
from vector_store import RedisVectorStore

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw09" / "raw"
QUERIES = [  # (kind, question)
    ("new", "How many units are available at listing S8110-A01?"),
    ("new", "Who is the landlord for listing S8110-A02?"),
    ("new", "What is the address of listing S8110-A03?"),
    ("new", "Is listing S8110-A04 currently available?"),
    ("exact duplicate", "How many units are available at listing S8110-A01?"),
    ("exact duplicate", "Is listing S8110-A04 currently available?"),
    ("paraphrase", "What's the number of open units for S8110-A01?"),
    ("paraphrase", "Which landlord owns listing S8110-A02?"),
    ("paraphrase", "Where is listing S8110-A03 located?"),
    ("new", "What is the maximum security deposit allowed in California?"),
    ("exact duplicate", "What is the address of listing S8110-A03?"),
    ("new", "How many units are available at listing S8110-A05?"),
]


def main() -> int:
    setup_logging(logging.INFO)
    threshold = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_THRESHOLD
    from db import db_session_basede26

    store = RedisVectorStore(redis.Redis.from_url(REDIS_URL, decode_responses=False))
    print(f"student: Alyssa Gomez  SID4={SID4}  threshold={threshold}  cleared {store.clear()} old cache entries")
    cache = SemanticCache(store, Embedder(), PipelineClient(), RecordRepo(db_session_basede26), threshold=threshold)
    stats, rows = CacheStats(), []
    for n, (kind, question) in enumerate(QUERIES, 1):
        result = cache.handle_query(question)
        stats.add(result)
        rows.append({"n": n, "kind": kind, **result.as_dict()})
        print(f"#{n:<2} {kind:<15} is_cached={result.is_cached!s:<5} similarity={result.similarity if result.similarity is None else round(result.similarity, 3)!s:<6} "
              f"latency={result.latency_ms:>9.1f} ms  answer={result.answer[:70]!r}")
    summary = stats.summary()
    print("\n=== Cache performance ===")
    print(f"hit rate: {summary['hit_rate_pct']}% ({summary['hits']}/{summary['queries']})")
    print(f"avg latency cached: {summary['avg_latency_cached_ms']} ms | not cached: {summary['avg_latency_not_cached_ms']} ms")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "part2_results.json").write_text(json.dumps({"threshold": threshold, "summary": summary, "queries": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())