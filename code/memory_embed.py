import hashlib
import re

import numpy as np


class Embedder:
    """sentence-transformers all-MiniLM-L6-v2, loaded lazily. Vectors are unit length."""
    def __init__(self, name="sentence-transformers/all-MiniLM-L6-v2"):
        self.name, self._m = name, None

    def embed(self, text: str) -> list:
        if self._m is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise RuntimeError("pip install sentence-transformers") from e
            self._m = SentenceTransformer(self.name)
        return self._m.encode(text, normalize_embeddings=True).tolist()


class HashEmbedder:
    """Offline bag-of-words hashing embedder (tests only)."""
    def __init__(self, dim=256):
        self.dim = dim

    def embed(self, text: str) -> list:
        v = np.zeros(self.dim)
        for w in re.findall(r"[a-z0-9$,.]+", text.lower()):
            w = w.strip(".,")
            if len(w) > 2:
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1
        n = np.linalg.norm(v)
        return (v / n if n else v).tolist()


def cosine_top_k(query_vec, items, k, min_score):
    """items: dicts with 'embedding'. Returns [(score, item)] best first."""
    if not items:
        return []
    mat = np.array([it["embedding"] for it in items], dtype=float)
    q = np.array(query_vec, dtype=float)
    sims = (mat @ q) / (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) or 1) + 1e-12)
    order = np.argsort(-sims)[:k]
    return [(float(sims[i]), items[i]) for i in order if sims[i] >= min_score]