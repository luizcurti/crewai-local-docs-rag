"""Vector database layer: local embeddings (Ollama nomic-embed-text) stored in ChromaDB.

Every record has an ID, a vector, its text and metadata. Two record types:
    type=function - an API entry (javascript_array_map)
    type=example  - one code example (javascript_array_map_example_01), with function_id
"""

import chromadb
import numpy as np
import requests
from chromadb.config import Settings

from config import CHROMA_DIR, COLLECTION, EMBED_MODEL, MODEL_KEEP_ALIVE, OLLAMA_URL

# nomic-embed-text was trained with different prefixes for documents and queries.
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
MAX_EMBED_CHARS = 1200  # the start of a chunk (name, signature, description) says what it is


def embed(texts: list[str], prefix: str) -> list[list[float]]:
    resp = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": [prefix + t[:MAX_EMBED_CHARS] for t in texts],
              "keep_alive": MODEL_KEEP_ALIVE},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def embed_query(text: str) -> list[float]:
    return embed([text], QUERY_PREFIX)[0]


_client = None


def get_collection(reset: bool = False):
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    if reset and COLLECTION in [c.name for c in _client.list_collections()]:
        _client.delete_collection(COLLECTION)
    # Chroma's index (HNSW) is approximate. With ef_search=200 (the default is 100) it returned
    # the same top 10 as an exact NumPy search for all of 20 test questions.
    return _client.get_or_create_collection(
        COLLECTION, metadata={"hnsw:space": "cosine", "hnsw:search_ef": 200, "hnsw:construction_ef": 200}
    )


def _where(**filters) -> dict | None:
    clauses = [{k: v} for k, v in filters.items() if v is not None]
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _hits(ids, documents, metadatas, scores) -> list[dict]:
    return [
        {"id": i, "text": d, "score": round(float(s), 4), **m}
        for i, d, m, s in zip(ids, documents, metadatas, scores)
    ]


def vector_search(query_vector: list[float], type: str, n: int = 5, language: str | None = None,
                  runtime: str | None = None) -> list[dict]:
    """Nearest records of one type; score is the cosine similarity (1 = identical)."""
    result = get_collection().query(
        query_embeddings=[query_vector], n_results=n, where=_where(type=type, language=language, runtime=runtime),
        include=["documents", "metadatas", "distances"],
    )
    return _hits(result["ids"][0], result["documents"][0], result["metadatas"][0],
                 [1 - d for d in result["distances"][0]])


def get_records(where: dict, query_vector: list[float] | None = None, limit: int = 200) -> list[dict]:
    """Records matching metadata exactly (e.g. every function named "map"), scored against
    the question when a query vector is given."""
    result = get_collection().get(where=where, limit=limit, include=["documents", "metadatas", "embeddings"])
    if not result["ids"]:
        return []
    if query_vector is None:
        scores = [0.0] * len(result["ids"])
    else:
        vectors = np.asarray(result["embeddings"], dtype=np.float32)
        q = np.asarray(query_vector, dtype=np.float32)
        scores = vectors @ q / (np.linalg.norm(vectors, axis=1) * np.linalg.norm(q))
    return _hits(result["ids"], result["documents"], result["metadatas"], scores)


def find_by_name(name: str, query_vector: list[float] | None = None, language: str | None = None) -> list[dict]:
    """Functions whose name or full name is `name`: "map" finds Array.prototype.map, Python's
    map() and Map; "Array.map" finds Array.prototype.map; "fs.readFile" finds fs.readFile."""
    name = name.lower().removesuffix("()")
    parts = name.split(".")
    clauses = [{"type": "function"}, {"$or": [{"full_name_lower": name}, {"name_lower": parts[-1]}]}]
    if language:
        clauses.append({"language": language})
    hits = get_records({"$and": clauses}, query_vector)
    if len(parts) > 1:
        # "Array.map", "path.join": the qualifier must match the object or the module.
        owner = parts[-2]
        hits = [h for h in hits if h["full_name_lower"] == name or owner in (h["object_lower"], h["module"].lower())]
    return hits


def examples_for(function_ids: list[str]) -> list[dict]:
    if not function_ids:
        return []
    hits = get_records({"$and": [{"type": "example"}, {"function_id": {"$in": function_ids}}]}, limit=200)
    return sorted(hits, key=lambda h: (function_ids.index(h["function_id"]), h["example_number"]))


def stats() -> dict:
    """Record counts per language and type, for the UI and preflight."""
    metas = get_collection().get(include=["metadatas"])["metadatas"]
    counts: dict[str, int] = {}
    for m in metas:
        key = f"{m['runtime']}/{m['type']}"
        counts[key] = counts.get(key, 0) + 1
    return {"total": len(metas), "by_source": counts}
