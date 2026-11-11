import logging
import time
from dataclasses import dataclass, field

from cache_config import DEFAULT_THRESHOLD
from listing_records import NO_RECORD, extract_listing_code, record_context, record_version
from tracing import record_span

logger = logging.getLogger("semantic_cache")


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 2)


@dataclass
class QueryResult:
    question: str
    answer: str
    is_cached: bool
    similarity: float | None
    latency_ms: float
    matched_query: str | None = None
    record_id: str = NO_RECORD
    data_version: str = NO_RECORD
    stale_invalidated: bool = False
    stored: bool = False
    timings: dict = field(default_factory=dict)
    trace_id: str | None = None

    def as_dict(self) -> dict:
        return {"question": self.question, "answer": self.answer, "is_cached": self.is_cached,
                "similarity": None if self.similarity is None else round(self.similarity, 4), "latency_ms": self.latency_ms,
                "matched_query": self.matched_query, "record_id": self.record_id, "data_version": self.data_version,
                "stale_invalidated": self.stale_invalidated, "stored": self.stored, "timings": self.timings,
                "trace_id": self.trace_id}


class CacheStats:
    """Hit rate and average latency for cached vs non-cached answers."""

    def __init__(self) -> None:
        self.results: list = []

    def add(self, result: QueryResult) -> None:
        self.results.append(result)

    def summary(self) -> dict:
        hits = [r.latency_ms for r in self.results if r.is_cached]
        misses = [r.latency_ms for r in self.results if not r.is_cached]
        avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
        return {"queries": len(self.results), "hits": len(hits), "misses": len(misses),
                "hit_rate_pct": round(100.0 * len(hits) / len(self.results), 1) if self.results else 0.0,
                "avg_latency_cached_ms": avg(hits), "avg_latency_not_cached_ms": avg(misses)}


class SemanticCache:
    """store: RedisVectorStore/MemoryVectorStore, embedder: .embed(text), agent_fn(question, context) -> (answer, ok), repo: RecordRepo or None."""

    def __init__(self, store, embedder, agent_fn, repo=None, threshold: float = DEFAULT_THRESHOLD, check_version: bool = False) -> None:
        self.store, self.embedder, self.agent_fn, self.repo = store, embedder, agent_fn, repo
        self.threshold, self.check_version = threshold, check_version

    def _is_stale(self, entry: dict) -> bool:
        if not self.check_version or self.repo is None or entry["record_id"] == NO_RECORD:
            return False
        return self.repo.version(entry["record_id"]) != entry["data_version"]

    def _lookup(self, question: str, timings: dict) -> tuple:
        """Embed, search and (when it would hit) version-check. Returns (vector, best entry, similarity, stale)."""
        t = time.perf_counter()
        vec = self.embedder.embed(question)
        timings["embed_ms"] = _ms(t)
        t = time.perf_counter()
        best = self.store.nearest(vec)
        timings["search_ms"] = _ms(t)
        sim = None if best is None else best["similarity"]
        stale = False
        if best is not None and sim >= self.threshold:
            t = time.perf_counter()
            stale = self._is_stale(best)
            timings["version_check_ms"] = _ms(t)
            if stale:
                self.store.delete(best["key"])
                logger.info("CACHE STALE similarity=%.4f record=%s data_version changed -> entry dropped, re-running agent", sim, best["record_id"])
        return vec, best, sim, stale

    def handle_query(self, question: str, trace_id: str | None = None) -> QueryResult:
        """Answer from the cache or, on a miss, through the agent pipeline. trace_id (the HW8 correlation_id) is passed on when given."""
        t_all, timings, wall = time.perf_counter(), {}, time.time()
        try:
            vec, best, sim, stale = self._lookup(question, timings)
        except Exception as exc:
            record_span(trace_id, "cache_lookup", wall, time.time(), "error", f"{type(exc).__name__}: {exc}")
            raise
        hit = best is not None and sim >= self.threshold and not stale
        record_span(trace_id, "cache_lookup", wall, time.time(), path="cache_hit" if hit else "cache_miss", cache_hit=hit,
                    similarity=None if sim is None else round(sim, 4), stale=stale or None)
        if hit:
            logger.info("CACHE HIT  similarity=%.4f threshold=%.2f matched=%r", sim, self.threshold, best["query"])
            return QueryResult(question, best["answer"], True, sim, _ms(t_all), best["query"], best["record_id"], best["data_version"],
                               timings=timings, trace_id=trace_id)
        if not stale:
            logger.info("CACHE MISS similarity=%s threshold=%.2f -> running HW8 agent pipeline", "n/a" if sim is None else f"{sim:.4f}", self.threshold)
        return self._miss(question, vec, sim, best, stale, timings, t_all, trace_id)

    def _miss(self, question, vec, sim, best, stale, timings, t_all, trace_id=None) -> QueryResult:
        code = extract_listing_code(question)
        rec = self.repo.get_by_code(code) if (self.repo is not None and code) else None
        t = time.perf_counter()
        context = record_context(rec) if rec else None
        answer, ok = self.agent_fn(question, context, trace_id=trace_id) if trace_id else self.agent_fn(question, context)
        timings["agent_ms"] = _ms(t)
        record_id, version = (code, record_version(rec)) if rec else (NO_RECORD, NO_RECORD)
        stored = False
        if ok and answer:
            self.store.add(question, answer, vec, record_id, version)
            stored = True
        return QueryResult(question, answer, False, sim, _ms(t_all), best["query"] if best else None, record_id, version,
                           stale_invalidated=stale, stored=stored, timings=timings, trace_id=trace_id)