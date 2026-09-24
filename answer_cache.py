"""Answer cache: a question asked again is answered from disk instead of the LLM.

The documentation does not change between ingestions, so the same question gets the same
answer. Each answer is stored as JSON under data/cache/, for ANSWER_CACHE_TTL seconds
(one day by default). The key is the normalized question plus the LLM and the vector
database version, so changing the model or re-indexing never serves a stale answer:

    "What is map used for?" == "what is map used for" == "  What is  map used for?? "

The key does not include the prompt: after changing it, clear the cache with
    python answer_cache.py
"""

import hashlib
import json
import re
import time
from pathlib import Path

from config import ANSWER_CACHE_DIR, ANSWER_CACHE_TTL, LLM_MODEL


def normalize(question: str) -> str:
    """Lowercase, single spaces, no trailing punctuation."""
    return re.sub(r"[\s?!.]+$", "", " ".join(question.lower().split()))


def _path(question: str, index_version: str) -> Path:
    key = json.dumps([normalize(question), LLM_MODEL, index_version])
    return ANSWER_CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"


def get(question: str, index_version: str) -> dict | None:
    """The cached answer's state, or None when there is none or it expired."""
    path = _path(question, index_version)
    try:
        entry = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if time.time() - entry["saved_at"] > ANSWER_CACHE_TTL:
        path.unlink(missing_ok=True)
        return None
    return entry["state"]


def put(question: str, index_version: str, state: dict) -> None:
    ANSWER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"saved_at": time.time(), "question": question, "model": LLM_MODEL, "state": state}
    _path(question, index_version).write_text(json.dumps(entry))


def clear() -> int:
    """Deletes every cached answer; returns how many there were."""
    paths = list(ANSWER_CACHE_DIR.glob("*.json")) if ANSWER_CACHE_DIR.exists() else []
    for path in paths:
        path.unlink(missing_ok=True)
    return len(paths)


if __name__ == "__main__":
    print(f"Deleted {clear()} cached answer(s).")
