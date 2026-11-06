import hashlib
import re

import numpy as np

from cache_config import EMBED_MODEL


class Embedder:
    """sentence-transformers/all-MiniLM-L6-v2, 384 dimensions, L2-normalised (so dot product == cosine similarity)."""

    def __init__(self, model_name: str = EMBED_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> np.ndarray:
        return np.asarray(self.model.encode(text, normalize_embeddings=True), dtype=np.float32)


class HashEmbedder:
    """Bag-of-words hashed into `dim` buckets, normalised. Deterministic, no model download."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for word in re.findall(r"[a-z0-9\-]+", text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec