"""Provider interfaces for model and memory backends."""

from __future__ import annotations

import json
import hashlib
import math
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol


class ModelProvider(Protocol):
    """Contract for model backends used by agents or hooks."""

    name: str

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        """Return a text completion for the prompt."""


@dataclass
class StaticModelProvider:
    """Deterministic model provider for tests and local scaffolding."""

    response: str
    name: str = "static"

    def complete(self, prompt: str, context: dict[str, Any] | None = None) -> str:
        return self.response


@dataclass(frozen=True)
class MemoryRecord:
    """One memory item stored by a MemoryProvider."""

    key: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class MemoryProvider(Protocol):
    """Contract for memory backends."""

    name: str

    def put(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        """Store one memory record."""

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        """Search memory records."""


class EmbeddingProvider(Protocol):
    """Contract for text embedding backends used by vector memory."""

    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]:
        """Return a numeric embedding vector for text."""


@dataclass
class KeywordMemoryProvider:
    """In-memory keyword search provider.

    This is intentionally simple and deterministic. Production deployments can
    replace it with a vector database provider behind the same protocol.
    """

    name: str = "keyword"
    records: dict[str, MemoryRecord] = field(default_factory=dict)

    def put(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        record = MemoryRecord(key=key, content=content, metadata=metadata or {})
        self.records[key] = record
        return record

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return []
        scored: list[tuple[int, MemoryRecord]] = []
        for record in self.records.values():
            haystack = f"{record.key} {record.content}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].created_at, item[1].key))
        return [record for _, record in scored[:top_k]]


@dataclass
class FileMemoryProvider:
    """File-backed keyword memory provider.

    The storage format is a small JSON document, suitable for local projects and
    tests. Larger deployments can replace this provider with SQLite, pgvector, or
    a vector database behind the same MemoryProvider protocol.
    """

    path: str | Path
    name: str = "file"
    records: dict[str, MemoryRecord] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    def put(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        record = MemoryRecord(key=key, content=content, metadata=metadata or {})
        self.records[key] = record
        self._save()
        return record

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return []
        scored: list[tuple[int, MemoryRecord]] = []
        for record in self.records.values():
            haystack = f"{record.key} {record.content}".lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].created_at, item[1].key))
        return [record for _, record in scored[:top_k]]

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        raw_records = data.get("records", {})
        self.records = {
            key: MemoryRecord(**record)
            for key, record in raw_records.items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "provider": self.name,
            "records": {
                key: asdict(record)
                for key, record in self.records.items()
            },
        }
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self.path)


@dataclass
class HashEmbeddingProvider:
    """Deterministic local embedding provider.

    This is not a replacement for model embeddings. It provides a stable,
    dependency-free vector backend for tests, local development, and adapter
    conformance. Production users can plug in an OpenAI/local embedding provider
    behind the same protocol.
    """

    dimensions: int = 128
    name: str = "hash"

    def embed(self, text: str) -> list[float]:
        if self.dimensions <= 0:
            raise ValueError("dimensions must be positive")
        vector = [0.0] * self.dimensions
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self.dimensions
            sign = 1.0 if (value >> 63) else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return vector
        return [value / norm for value in vector]

    def _features(self, text: str) -> list[str]:
        normalized = " ".join(text.lower().split())
        tokens = re.findall(r"[\w]+", normalized, flags=re.UNICODE)
        features = [f"w:{token}" for token in tokens]
        compact = re.sub(r"\s+", "", normalized)
        if len(compact) >= 3:
            features.extend(
                f"g:{compact[index:index + 3]}"
                for index in range(len(compact) - 2)
            )
        elif compact:
            features.append(f"g:{compact}")
        return features


@dataclass
class VectorMemoryProvider:
    """File-backed vector memory provider.

    Records and embeddings are persisted as JSON. The default
    HashEmbeddingProvider keeps this implementation dependency-free; pass a real
    embedding provider for production semantic retrieval.
    """

    path: str | Path | None = None
    embedding_provider: EmbeddingProvider = field(default_factory=HashEmbeddingProvider)
    name: str = "vector"
    records: dict[str, MemoryRecord] = field(default_factory=dict, init=False)
    vectors: dict[str, list[float]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path) if self.path is not None else None
        self._load()

    def put(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        record = MemoryRecord(key=key, content=content, metadata=metadata or {})
        self.records[key] = record
        self.vectors[key] = self.embedding_provider.embed(f"{key}\n{content}")
        self._save()
        return record

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        return [record for record, _ in self.search_with_scores(query, top_k=top_k)]

    def search_with_scores(self, query: str, top_k: int = 5) -> list[tuple[MemoryRecord, float]]:
        if not query.strip() or top_k <= 0:
            return []
        query_vector = self.embedding_provider.embed(query)
        scored: list[tuple[MemoryRecord, float]] = []
        for key, record in self.records.items():
            vector = self.vectors.get(key)
            if not vector:
                vector = self.embedding_provider.embed(f"{record.key}\n{record.content}")
                self.vectors[key] = vector
            score = _cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append((record, score))
        scored.sort(key=lambda item: (-item[1], item[0].created_at, item[0].key))
        return scored[:top_k]

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        raw_records = data.get("records", {})
        raw_vectors = data.get("vectors", {})
        self.records = {
            key: MemoryRecord(**record)
            for key, record in raw_records.items()
        }
        dimensions = self.embedding_provider.dimensions
        self.vectors = {}
        for key, record in self.records.items():
            vector = raw_vectors.get(key)
            if (
                isinstance(vector, list)
                and len(vector) == dimensions
                and all(isinstance(value, (int, float)) for value in vector)
            ):
                self.vectors[key] = [float(value) for value in vector]
            else:
                self.vectors[key] = self.embedding_provider.embed(f"{record.key}\n{record.content}")

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "provider": self.name,
            "embedding_provider": self.embedding_provider.name,
            "dimensions": self.embedding_provider.dimensions,
            "records": {
                key: asdict(record)
                for key, record in self.records.items()
            },
            "vectors": self.vectors,
        }
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self.path)


@dataclass
class SqliteVectorMemoryProvider:
    """SQLite-backed vector memory provider.

    This keeps the framework dependency-free while avoiding one large JSON file
    for long-running agents. Search is exact cosine scan over stored vectors;
    production deployments can replace this with pgvector/Qdrant/etc. behind the
    same MemoryProvider contract.
    """

    path: str | Path
    embedding_provider: EmbeddingProvider = field(default_factory=HashEmbeddingProvider)
    name: str = "sqlite-vector"
    connection: sqlite3.Connection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def put(self, key: str, content: str, metadata: dict[str, Any] | None = None) -> MemoryRecord:
        record = MemoryRecord(key=key, content=content, metadata=metadata or {})
        vector = self.embedding_provider.embed(f"{key}\n{content}")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO memory_records (
                    key, content, metadata_json, created_at, vector_json,
                    embedding_provider, dimensions
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    metadata_json = excluded.metadata_json,
                    created_at = excluded.created_at,
                    vector_json = excluded.vector_json,
                    embedding_provider = excluded.embedding_provider,
                    dimensions = excluded.dimensions
                """,
                (
                    record.key,
                    record.content,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.created_at,
                    json.dumps(vector, ensure_ascii=False),
                    self.embedding_provider.name,
                    self.embedding_provider.dimensions,
                ),
            )
        return record

    def search(self, query: str, top_k: int = 5) -> list[MemoryRecord]:
        return [record for record, _ in self.search_with_scores(query, top_k=top_k)]

    def search_with_scores(self, query: str, top_k: int = 5) -> list[tuple[MemoryRecord, float]]:
        if not query.strip() or top_k <= 0:
            return []
        query_vector = self.embedding_provider.embed(query)
        scored: list[tuple[MemoryRecord, float]] = []
        rows = self.connection.execute(
            """
            SELECT key, content, metadata_json, created_at, vector_json,
                   embedding_provider, dimensions
            FROM memory_records
            """
        ).fetchall()
        for row in rows:
            record = MemoryRecord(
                key=row["key"],
                content=row["content"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                created_at=float(row["created_at"]),
            )
            vector = self._row_vector(row, record)
            score = _cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append((record, score))
        scored.sort(key=lambda item: (-item[1], item[0].created_at, item[0].key))
        return scored[:top_k]

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SqliteVectorMemoryProvider":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    vector_json TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    dimensions INTEGER NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_records_created_at
                ON memory_records(created_at)
                """
            )

    def _row_vector(self, row: sqlite3.Row, record: MemoryRecord) -> list[float]:
        if (
            row["embedding_provider"] == self.embedding_provider.name
            and int(row["dimensions"]) == self.embedding_provider.dimensions
        ):
            try:
                vector = json.loads(row["vector_json"])
                if (
                    isinstance(vector, list)
                    and len(vector) == self.embedding_provider.dimensions
                    and all(isinstance(value, (int, float)) for value in vector)
                ):
                    return [float(value) for value in vector]
            except json.JSONDecodeError:
                pass
        vector = self.embedding_provider.embed(f"{record.key}\n{record.content}")
        with self.connection:
            self.connection.execute(
                """
                UPDATE memory_records
                SET vector_json = ?, embedding_provider = ?, dimensions = ?
                WHERE key = ?
                """,
                (
                    json.dumps(vector, ensure_ascii=False),
                    self.embedding_provider.name,
                    self.embedding_provider.dimensions,
                    record.key,
                ),
            )
        return vector


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    return dot / (left_norm * right_norm)
