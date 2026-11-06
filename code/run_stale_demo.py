import json
import logging
import sys
from pathlib import Path

import redis

from agent_adapter import PipelineClient
from cache_config import REDIS_URL, SID4, setup_logging
from embedder import Embedder
from listing_records import RecordRepo, ground_truth
from semantic_cache import SemanticCache
from vector_store import RedisVectorStore

RAW = Path(__file__).resolve().parent.parent / "reports" / "hw09" / "raw"
CODE, QUESTION = "S8110-A01", "How many units are available at listing S8110-A01?"


def show(step: str, result, repo) -> dict:
    truth = ground_truth(QUESTION, repo.get_by_code(CODE))
    print(f"{step}\n   is_cached={result.is_cached} similarity={None if result.similarity is None else round(result.similarity, 3)} "
          f"stale_invalidated={result.stale_invalidated}\n   answer returned : {result.answer}\n   database says   : {truth}\n")
    return {"step": step, **result.as_dict(), "database_truth": truth}


def main() -> int:
    setup_logging(logging.INFO)
    from db import db_session_basede26

    repo = RecordRepo(db_session_basede26)
    repo.ensure_demo_listings()  # resets A01 to 3 units
    store = RedisVectorStore(redis.Redis.from_url(REDIS_URL, decode_responses=False))
    store.clear()
    embedder, agent = Embedder(), PipelineClient()
    no_check = SemanticCache(store, embedder, agent, repo, threshold=0.85, check_version=False)
    with_check = SemanticCache(store, embedder, agent, repo, threshold=0.85, check_version=True)
    print(f"student: Alyssa Gomez  SID4={SID4}\n")
    log = [show("1. first ask (cache miss, answer stored with data_version)", no_check.handle_query(QUESTION), repo)]
    repo.set_units(CODE, 0)
    print(f"-- UPDATE listings SET available_units = 0 WHERE listing_code = '{CODE}'  (cached answer is now stale)\n")
    log.append(show("2. ask again, NO invalidation -> stale hit", no_check.handle_query(QUESTION), repo))
    log.append(show("3. ask again, data-version check -> stale entry dropped, agent re-run", with_check.handle_query(QUESTION), repo))
    log.append(show("4. ask again -> hit with the fresh answer", with_check.handle_query(QUESTION), repo))
    repo.ensure_demo_listings()  # put the record back
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "stale_demo.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())