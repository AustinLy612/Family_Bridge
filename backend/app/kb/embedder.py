"""Embedding providers (Plan §5.3 step 6; D45).

`FastEmbedder` runs intfloat/multilingual-e5-large locally through fastembed/ONNX. e5 expects
"passage: " and "query: " prefixes, and fastembed does not add them, so we do. `HashEmbedder`
is a deterministic offline fake for tests (character n-gram feature hashing): no download, but
still ranks texts that share words higher, so retrieval tests are meaningful.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.models.knowledge import EMBEDDING_DIM
from app.settings import Settings


class Embedder(Protocol):
    name: str
    dim: int

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _unit(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [float(x) / n for x in v]


class HashEmbedder:
    name = "hash-ngram-v1"
    dim = EMBEDDING_DIM

    def _vec(self, text: str) -> list[float]:
        t = "".join(ch for ch in text.casefold() if ch.isalnum())
        v = [0.0] * self.dim
        for n in (1, 2):
            for i in range(len(t) - n + 1):
                d = hashlib.blake2b(t[i : i + n].encode(), digest_size=4).digest()
                idx = int.from_bytes(d[:3], "big") % self.dim
                v[idx] += 1.0 if d[3] & 1 else -1.0
        return _unit(v)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class FastEmbedder:
    dim = EMBEDDING_DIM

    def __init__(self, model: str, cache_dir: Path) -> None:
        self.name = model
        self._cache_dir = cache_dir
        self._model: object | None = None
        self._lock = threading.Lock()

    def _get(self) -> object:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(model_name=self.name, cache_dir=str(self._cache_dir))
            return self._model

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._get()
        vecs = model.embed(list(texts), batch_size=16)  # type: ignore[attr-defined]
        out = [_unit(v.tolist()) for v in vecs]
        if out and len(out[0]) != self.dim:
            raise RuntimeError(f"{self.name} returned {len(out[0])} dims, expected {self.dim}")
        return out

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"query: {text}"])[0]


_cache: dict[tuple[str, str, str], Embedder] = {}
_cache_lock = threading.Lock()


def get_embedder(settings: Settings) -> Embedder:
    key = (settings.embedding_provider, settings.embedding_model, str(settings.embedding_cache_dir))
    with _cache_lock:
        if key not in _cache:
            _cache[key] = (
                HashEmbedder()
                if settings.embedding_provider == "hash"
                else FastEmbedder(settings.embedding_model, settings.embedding_cache_dir)
            )
        return _cache[key]
