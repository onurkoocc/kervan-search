"""Vector search providers.

`SimulatedProvider` runs in process and is what Kervan uses. `HttpProvider`
stands for an external vector search service; it is configured but not used in
Kervan (SPEC §7).
"""

import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

from .text import tokens

SCORE_DIGITS = 4


@dataclass(frozen=True)
class IndexDoc:
    id: str
    text: str


@dataclass(frozen=True)
class Match:
    id: str
    score: float


class ProviderError(Exception):
    """The provider could not answer; the API reports it as 502."""


class VectorProvider(Protocol):
    name: str

    def index(self, docs: Sequence[IndexDoc]) -> None:
        """Replace the indexed corpus with `docs`."""
        ...

    def query(self, text: str, k: int) -> list[Match]:
        """At most `k` matches with a positive score, best first."""
        ...


def rank(scores: dict[str, float], k: int) -> list[Match]:
    """Positive scores only, best first, ties broken by id."""
    matches = [Match(i, s) for i, s in scores.items() if s > 0]
    matches.sort(key=lambda m: (-m.score, m.id))
    return matches[:k]


class SimulatedProvider:
    """Deterministic hashed bag-of-words embeddings with tf-idf weights and cosine similarity.

    Buckets come from BLAKE2b, never from Python's salted `hash()`, so the same
    corpus and query give the same scores on every machine and in every process.
    """

    name = "simulated"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self._idf: dict[str, float] = {}
        self._unseen_idf = 1.0
        self._vectors: dict[str, dict[int, float]] = {}

    def _bucket(self, term: str) -> tuple[int, float]:
        digest = hashlib.blake2b(term.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dim, (1.0 if value >> 63 else -1.0)

    def embed(self, text: str) -> dict[int, float]:
        """A sparse, L2-normalized vector."""
        vector: dict[int, float] = {}
        for term, count in sorted(Counter(tokens(text)).items()):
            weight = (1.0 + math.log(count)) * self._idf.get(term, self._unseen_idf)
            bucket, sign = self._bucket(term)
            vector[bucket] = vector.get(bucket, 0.0) + sign * weight
        norm = math.sqrt(sum(v * v for v in vector.values()))
        return {b: v / norm for b, v in vector.items()} if norm else {}

    def index(self, docs: Sequence[IndexDoc]) -> None:
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(set(tokens(doc.text)))
        n = len(docs)
        # Smoothed idf; a term no document contains gets the highest weight.
        self._idf = {term: math.log((n + 1) / (d + 1)) + 1.0 for term, d in df.items()}
        self._unseen_idf = math.log(n + 1) + 1.0
        self._vectors = {doc.id: self.embed(doc.text) for doc in docs}

    def query(self, text: str, k: int) -> list[Match]:
        q = self.embed(text)
        scores = {
            doc_id: round(sum(w * vec.get(b, 0.0) for b, w in q.items()), SCORE_DIGITS)
            for doc_id, vec in self._vectors.items()
        }
        return rank(scores, k)


class HttpProvider:
    """Client for an external vector search API.

    POST {base}/v1/index  {"documents": [{"id", "text"}]}       -> 2xx
    POST {base}/v1/query  {"query": text, "top_k": k}            -> {"matches": [{"id", "score"}]}
    """

    name = "http"

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    def _post(self, path: str, payload: dict) -> httpx.Response:
        try:
            response = self._client.post(path, json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"{path}: {type(e).__name__}") from e
        if response.status_code // 100 != 2:
            raise ProviderError(f"{path}: HTTP {response.status_code}")
        return response

    def index(self, docs: Sequence[IndexDoc]) -> None:
        self._post("/v1/index", {"documents": [{"id": d.id, "text": d.text} for d in docs]})

    def query(self, text: str, k: int) -> list[Match]:
        response = self._post("/v1/query", {"query": text, "top_k": k})
        try:
            raw = response.json()["matches"]
            scores = {str(m["id"]): float(m["score"]) for m in raw}
        except (ValueError, KeyError, TypeError) as e:
            raise ProviderError(f"/v1/query: malformed answer ({type(e).__name__})") from e
        if not all(math.isfinite(s) for s in scores.values()):
            raise ProviderError("/v1/query: malformed answer (non-finite score)")
        scores = {i: round(s, SCORE_DIGITS) for i, s in scores.items()}
        return rank(scores, k)

    def close(self) -> None:
        self._client.close()
