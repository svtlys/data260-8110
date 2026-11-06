import logging

from listing_cache import ListingCache


class FakeRedis:
    def __init__(self):
        self.data = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]


class FakeRepo:
    def __init__(self, fail=False):
        self.saved, self.fail = [], fail

    def save_views(self, listing_id, count):
        if self.fail:
            raise RuntimeError("database down")
        self.saved.append((listing_id, count))
        return True


def test_returns_running_total_and_key_has_prefix():
    cache = ListingCache(FakeRedis(), FakeRepo())
    assert [cache.increment_listing_views(7) for _ in range(3)] == [1, 2, 3]
    assert ListingCache.views_key(7) == "s8110:views:listing:7"
    assert all(k.startswith("s8110:") for k in cache.redis_client.data)


def test_syncs_to_database_only_every_10th_access():
    repo = FakeRepo()
    cache = ListingCache(FakeRedis(), repo)
    for _ in range(25):
        cache.increment_listing_views(7)
    assert repo.saved == [(7, 10), (7, 20)]


def test_logs_synced_message(caplog=None):
    records = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    log = logging.getLogger("listing_cache")
    log.setLevel(logging.INFO)
    handler = Grab()
    log.addHandler(handler)
    cache = ListingCache(FakeRedis(), FakeRepo())
    for _ in range(10):
        cache.increment_listing_views(1)
    log.removeHandler(handler)
    assert any("Synced views to database" in m for m in records)


def test_counter_survives_database_failure():
    cache = ListingCache(FakeRedis(), FakeRepo(fail=True))
    assert [cache.increment_listing_views(1) for _ in range(12)][-1] == 12


def test_each_listing_has_its_own_counter():
    cache = ListingCache(FakeRedis(), FakeRepo())
    cache.increment_listing_views(1)
    cache.increment_listing_views(1)
    assert cache.increment_listing_views(2) == 1