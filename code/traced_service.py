import logging
import time
import uuid

from tracing import record_span

logger = logging.getLogger("traced_service")


class TracedService:
    """cache: a SemanticCache whose agent_fn accepts trace_id (agent_adapter.PipelineClient)."""

    def __init__(self, cache) -> None:
        self.cache = cache

    def ask(self, question: str, trace_id: str | None = None):
        """Return the QueryResult (result.trace_id is set). Errors are recorded on the request span and re-raised."""
        trace_id = trace_id or str(uuid.uuid4())
        start = time.time()
        try:
            result = self.cache.handle_query(question, trace_id=trace_id)
        except Exception as exc:
            record_span(trace_id, "request", start, time.time(), "error", f"{type(exc).__name__}: {exc}")
            raise
        record_span(trace_id, "request", start, time.time(), path="cache_hit" if result.is_cached else "cache_miss", approved=bool(result.answer))
        return result


def build_service(threshold: float = 0.85, timeout: float = 300.0):
    """Production wiring (needs Redis Stack, MySQL, Kafka and the three agents): returns (TracedService, store, agent_client)."""
    import redis

    from agent_adapter import PipelineClient
    from cache_config import REDIS_URL
    from db import db_session_basede26
    from embedder import Embedder
    from listing_records import RecordRepo
    from semantic_cache import SemanticCache
    from vector_store import RedisVectorStore

    store = RedisVectorStore(redis.Redis.from_url(REDIS_URL, decode_responses=False))
    client = PipelineClient(timeout=timeout)
    cache = SemanticCache(store, Embedder(), client, RecordRepo(db_session_basede26), threshold=threshold, check_version=True)
    return TracedService(cache), store, client