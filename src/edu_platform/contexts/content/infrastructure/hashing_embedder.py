"""Embedder adapter: deterministic feature hashing (no model download, no GPU).

Lower-cased word unigrams and bigrams are hashed (blake2b, signed) into a fixed number of
dimensions and L2-normalised. Lexical, not semantic: "join" and "merge" do not meet. It
keeps the vector path (kNN, hybrid ranking) real and reproducible; swapping in a sentence
embedding model is a new adapter behind the same port, with a new ``model`` name so old
and new vectors are never mixed.
"""

from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise

_WORD = re.compile(r"[a-z0-9_]+")


class HashingEmbedder:
    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions
        self.model = f"hashing-v1-{dimensions}"

    def _features(self, text: str) -> list[str]:
        words = _WORD.findall(text.lower())
        return words + [f"{a} {b}" for a, b in pairwise(words)]

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            sign = 1.0 if value & 1 else -1.0
            vector[(value >> 1) % self.dimensions] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]
