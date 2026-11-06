import logging

from cache_config import PREFIX, SYNC_EVERY

logger = logging.getLogger("listing_cache")


class SqlViewsRepo:
    """Database side: one UPDATE per sync. Works on MySQL (s8110_rel) and SQLite (tests)."""

    def __init__(self, engine, session_factory) -> None:
        self.engine, self.session_factory = engine, session_factory

    def ensure_column(self) -> bool:
        """Add listings.views (INT NOT NULL DEFAULT 0) if it is missing. Returns True when it had to be added."""
        from sqlalchemy import inspect, text

        if "views" in {c["name"] for c in inspect(self.engine).get_columns("listings")}:
            return False
        with self.engine.begin() as conn:
            conn.execute(text("ALTER TABLE listings ADD COLUMN views INT NOT NULL DEFAULT 0"))
        return True

    def save_views(self, listing_id: int, count: int) -> bool:
        """UPDATE the row; True when a row was updated."""
        from sqlalchemy import text

        with self.session_factory() as session:
            result = session.execute(text("UPDATE listings SET views = :c WHERE id = :i"), {"c": count, "i": listing_id})
            session.commit()
            return result.rowcount > 0

    def get_views(self, listing_id: int) -> int | None:
        from sqlalchemy import text

        with self.session_factory() as session:
            row = session.execute(text("SELECT views FROM listings WHERE id = :i"), {"i": listing_id}).first()
            return None if row is None else int(row[0])


class ListingCache:
    """Database/cache class for Listing. `redis_client` is a redis.Redis(decode_responses=True); `repo` has save_views()."""

    def __init__(self, redis_client, repo, sync_every: int = SYNC_EVERY) -> None:
        self.redis_client, self.repo, self.sync_every = redis_client, repo, sync_every

    @staticmethod
    def views_key(listing_id) -> str:
        return f"{PREFIX}:views:listing:{listing_id}"

    def increment_listing_views(self, listing_id) -> int:
        """Count one access. Returns the current total; every 10th access also persists it to the database."""
        key = self.views_key(listing_id)
        count = int(self.redis_client.incr(key))
        if count % self.sync_every == 0:
            self._sync(listing_id, count)
        return count

    def _sync(self, listing_id, count: int) -> None:
        try:
            if self.repo.save_views(listing_id, count):
                logger.info("Synced views to database (listing_id=%s, views=%d)", listing_id, count)
            else:
                logger.warning("Listing %s not found in database - views not persisted", listing_id)
        except Exception as exc:  # the counter must keep working when the database is down
            logger.warning("Could not sync views to database (%s); Redis still holds %d", exc, count)