"""Checks the local services before a run and explains how to fix what is missing.

Usage:
    python preflight.py
"""

import sys

import requests

from config import EMBED_MODEL, LLM_MODEL, OLLAMA_URL


def ollama_problems(need_llm: bool = True) -> list[str]:
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
    except requests.RequestException:
        return [f"Ollama is not reachable at {OLLAMA_URL}. Start it with: brew services start ollama (or: ollama serve)"]
    installed = {m["name"] for m in tags.get("models", [])}
    installed |= {name.removesuffix(":latest") for name in installed}
    needed = [EMBED_MODEL] + ([LLM_MODEL] if need_llm else [])
    return [_install_hint(m) for m in needed if m not in installed]


# The project's models are built from an Ollama model and a Modelfile (context size, answer cap).
MODELFILES = {"docs-rag-qwen2.5-3b": ("qwen2.5:3b", "ollama/Modelfile"), "docs-rag-qwen2.5": ("qwen2.5:7b", "ollama/Modelfile.7b")}


def _install_hint(model: str) -> str:
    if model in MODELFILES:
        base, modelfile = MODELFILES[model]
        return f"Model '{model}' is not created. Run: ollama pull {base} && ollama create {model} -f {modelfile}"
    return f"Model '{model}' is not installed. Run: ollama pull {model}"


def index_problems() -> list[str]:
    from store import get_collection

    if get_collection().count() == 0:
        return ["The vector database is empty. Run: python ingest.py"]
    return []


def check_services(need_index: bool = True, need_llm: bool = True) -> None:
    """Exits with a clear message when a required service is missing."""
    problems = ollama_problems(need_llm)
    if not problems and need_index:
        problems += index_problems()
    if problems:
        print("Cannot run:\n" + "\n".join(f"  - {p}" for p in problems), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    check_services()
    print(f"OK: Ollama ({LLM_MODEL}, {EMBED_MODEL}) and the vector database are ready.")
