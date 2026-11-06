import yaml

from cost_model import choose_threshold, total_cost
from embedder import HashEmbedder
from listing_records import extract_listing_code, ground_truth, record_context, record_version
from semantic_cache import CacheStats, SemanticCache
from vector_store import MemoryVectorStore, parse_search_reply

Q = "How many units are available at listing S8110-A01?"


class FakeRepo:
    def __init__(self):
        self.rows = {"S8110-A01": {"address": "450 Maple Ave", "available_units": 3, "landlord_name": "Bayview", "listing_code": "S8110-A01"}}

    def get_by_code(self, code):
        return dict(self.rows[code]) if code in self.rows else None

    def version(self, code):
        return record_version(self.get_by_code(code))


class FakeAgent:
    def __init__(self, repo):
        self.calls, self.repo = 0, repo

    def __call__(self, question, context):
        self.calls += 1
        return f"answer from facts: {context or 'generic'}", True


def make(threshold=0.85, check_version=False):
    repo = FakeRepo()
    agent = FakeAgent(repo)
    return SemanticCache(MemoryVectorStore(), HashEmbedder(), agent, repo, threshold, check_version), agent, repo


def test_miss_then_exact_duplicate_hits_without_running_agent():
    cache, agent, _ = make()
    first, second = cache.handle_query(Q), cache.handle_query(Q)
    assert first.is_cached is False and second.is_cached is True
    assert second.similarity > 0.99 and agent.calls == 1 and second.answer == first.answer


def test_unrelated_question_misses():
    cache, agent, _ = make()
    cache.handle_query(Q)
    other = cache.handle_query("What is the capital of France and its population?")
    assert other.is_cached is False and agent.calls == 2


def test_threshold_controls_hits():
    low, _, _ = make(threshold=0.3)
    high, _, _ = make(threshold=0.99)
    para = "What's the number of open units for S8110-A01?"
    for cache in (low, high):
        cache.handle_query(Q)
    assert low.handle_query(para).is_cached is True
    assert high.handle_query(para).is_cached is False


def test_stale_hit_without_invalidation_and_refresh_with_version_check():
    cache, agent, repo = make(check_version=False)
    first = cache.handle_query(Q)
    repo.rows["S8110-A01"]["available_units"] = 0
    stale = cache.handle_query(Q)
    assert stale.is_cached and stale.answer == first.answer  # the stale hit
    cache.check_version = True
    fresh = cache.handle_query(Q)
    assert fresh.is_cached is False and fresh.stale_invalidated and "available_units=0" in fresh.answer
    assert cache.handle_query(Q).is_cached is True and agent.calls == 2


def test_stats_hit_rate_and_latencies():
    cache, _, _ = make()
    stats = CacheStats()
    for q in (Q, Q, Q):
        stats.add(cache.handle_query(q))
    summary = stats.summary()
    assert summary["hits"] == 2 and summary["misses"] == 1 and summary["hit_rate_pct"] == 66.7
    assert summary["avg_latency_cached_ms"] is not None and summary["avg_latency_not_cached_ms"] is not None


def test_helpers_and_cost_model():
    assert extract_listing_code("is s8110-a07 free?") == "S8110-A07" and extract_listing_code("hello") is None
    rec = FakeRepo().get_by_code("S8110-A01")
    assert "3 unit" in ground_truth(Q, rec) and "available_units=3" in record_context(rec)
    assert record_version(rec) != record_version({**rec, "available_units": 0})
    assert total_cost(10, 0, 30) == 0.301
    rows = [{"threshold": 0.75, "hits": 30, "false_hits": 10, "misses": 10}, {"threshold": 0.95, "hits": 10, "false_hits": 0, "misses": 30}]
    assert choose_threshold(rows)["threshold"] == 0.95


def test_search_reply_parser():
    reply = [1, b"s8110:cache:abc", [b"query", b"q?", b"answer", b"a.", b"score", b"0.1"]]
    assert parse_search_reply(reply) == [{"query": "q?", "answer": "a.", "score": "0.1", "key": "s8110:cache:abc"}]
    assert parse_search_reply([0]) == []


def test_cases_file_is_balanced_and_consistent():
    import os
    spec = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "cache_cases.yaml"), encoding="utf-8"))
    cats = [c["category"] for c in spec["cases"]]
    assert len(cats) == 40 and all(cats.count(k) == 10 for k in set(cats)) and len(set(cats)) == 4
    seed_keys = {s["answer_key"] for s in spec["seeds"]}
    for c in spec["cases"]:
        assert (c["expected"] == "hit") == (c["category"] in ("exact_duplicate", "paraphrase"))
        if c["category"] in ("similar_different", "unrelated"):
            assert c["answer_key"] not in seed_keys