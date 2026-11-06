import time
import uuid

import numpy as np

from cache_config import EMBED_DIM, PREFIX

INDEX = f"{PREFIX}:idx:cache"
KEY_PREFIX = f"{PREFIX}:cache:"


def _s(value) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


def parse_search_reply(reply) -> list:
    """FT.SEARCH reply [total, key, [field, value, ...], ...] -> list of dicts (with the key under 'key')."""
    out = []
    for i in range(1, len(reply), 2):
        fields = reply[i + 1]
        row = {_s(fields[j]): _s(fields[j + 1]) for j in range(0, len(fields), 2)}
        row["key"] = _s(reply[i])
        out.append(row)
    return out


class RedisVectorStore:
    """`client` must be redis.Redis(..., decode_responses=False) because vectors are binary."""

    def __init__(self, client, dim: int = EMBED_DIM) -> None:
        self.client, self.dim = client, dim
        self.ensure_index()

    def ensure_index(self) -> None:
        try:
            self.client.execute_command("FT.INFO", INDEX)
            return
        except Exception:
            pass
        self.client.execute_command("FT.CREATE", INDEX, "ON", "HASH", "PREFIX", "1", KEY_PREFIX, "SCHEMA",
                                    "query", "TEXT", "answer", "TEXT", "record_id", "TAG", "data_version", "TAG",
                                    "embedding", "VECTOR", "FLAT", "6", "TYPE", "FLOAT32", "DIM", str(self.dim), "DISTANCE_METRIC", "COSINE")

    def add(self, query: str, answer: str, vec, record_id: str, data_version: str) -> str:
        key = KEY_PREFIX + uuid.uuid4().hex[:12]
        self.client.hset(key, mapping={"query": query, "answer": answer, "record_id": record_id, "data_version": data_version,
                                       "created_at": str(int(time.time())), "embedding": np.asarray(vec, dtype=np.float32).tobytes()})
        return key

    def nearest(self, vec) -> dict | None:
        reply = self.client.execute_command("FT.SEARCH", INDEX, "*=>[KNN 1 @embedding $vec AS score]", "PARAMS", "2", "vec",
                                            np.asarray(vec, dtype=np.float32).tobytes(), "SORTBY", "score", "RETURN", "5",
                                            "query", "answer", "record_id", "data_version", "score", "DIALECT", "2")
        rows = parse_search_reply(reply)
        if not rows:
            return None
        row = rows[0]
        row["similarity"] = 1.0 - float(row.pop("score"))
        return row

    def delete(self, key: str) -> None:
        self.client.delete(key)

    def clear(self) -> int:
        keys = list(self.client.scan_iter(match=KEY_PREFIX + "*"))
        if keys:
            self.client.delete(*keys)
        return len(keys)

    def count(self) -> int:
        return sum(1 for _ in self.client.scan_iter(match=KEY_PREFIX + "*"))


class MemoryVectorStore:
    """In-memory twin of RedisVectorStore."""

    def __init__(self) -> None:
        self.rows: dict = {}

    def add(self, query: str, answer: str, vec, record_id: str, data_version: str) -> str:
        key = KEY_PREFIX + uuid.uuid4().hex[:12]
        self.rows[key] = {"query": query, "answer": answer, "record_id": record_id, "data_version": data_version,
                          "vec": np.asarray(vec, dtype=np.float32)}
        return key

    def nearest(self, vec) -> dict | None:
        best, best_sim = None, -2.0
        for key, row in self.rows.items():
            sim = float(np.dot(row["vec"], np.asarray(vec, dtype=np.float32)))
            if sim > best_sim:
                best, best_sim = key, sim
        if best is None:
            return None
        row = self.rows[best]
        return {"key": best, "query": row["query"], "answer": row["answer"], "record_id": row["record_id"],
                "data_version": row["data_version"], "similarity": best_sim}

    def delete(self, key: str) -> None:
        self.rows.pop(key, None)

    def clear(self) -> int:
        n = len(self.rows)
        self.rows.clear()
        return n

    def count(self) -> int:
        return len(self.rows)