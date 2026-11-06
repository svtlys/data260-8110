import logging
import time
from dataclasses import dataclass, field

from cache_config import DEFAULT_THRESHOLD
from listing_records import NO_RECORD, extract_listing_code, record_context, record_version

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

    def as_dict(self) -> dict:
        return {"question": self.question, "answer": self.answer, "is_cached": self.is_cached,
                "similarity": None if self.similarity is None else round(self.similarity, 4), "latency_ms": self.latency_ms,
                "matched_query": self.matched_query, "record_id": self.record_id, "data_version": self.data_version,
                "stale_invalidated": self.stale_invalidated, "stored": self.stored, "timings": self.timings}


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

    def handle_query(self, question: str) -> QueryResult:
        t_all, timings = time.perf_counter(), {}
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
            if not stale:
                logger.info("CACHE HIT  similarity=%.4f threshold=%.2f matched=%r", sim, self.threshold, best["query"])
                return QueryResult(question, best["answer"], True, sim, _ms(t_all), best["query"], best["record_id"], best["data_version"],
                                   timings=timings)
            self.store.delete(best["key"])
            logger.info("CACHE STALE similarity=%.4f record=%s data_version changed -> entry dropped, re-running agent", sim, best["record_id"])
        else:
            logger.info("CACHE MISS similarity=%s threshold=%.2f -> running HW8 agent pipeline", "n/a" if sim is None else f"{sim:.4f}", self.threshold)
        return self._miss(question, vec, sim, best, stale, timings, t_all)

    def _miss(self, question, vec, sim, best, stale, timings, t_all) -> QueryResult:
        code = extract_listing_code(question)
        rec = self.repo.get_by_code(code) if (self.repo is not None and code) else None
        t = time.perf_counter()
        answer, ok = self.agent_fn(question, record_context(rec) if rec else None)
        timings["agent_ms"] = _ms(t)
        record_id, version = (code, record_version(rec)) if rec else (NO_RECORD, NO_RECORD)
        stored = False
        if ok and answer:
            self.store.add(question, answer, vec, record_id, version)
            stored = True
        return QueryResult(question, answer, False, sim, _ms(t_all), best["query"] if best else None, record_id, version,
                           stale_invalidated=stale, stored=stored, timings=timings)