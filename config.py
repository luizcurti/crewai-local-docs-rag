"""Settings shared by ingestion and querying."""

import os
from pathlib import Path

# Fully local: turn off CrewAI and ChromaDB telemetry.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("CREWAI_DISABLE_VERSION_CHECK", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

ROOT = Path(__file__).parent
RAW_DIR = ROOT / "data" / "raw"        # downloaded documentation
CHROMA_DIR = ROOT / "data" / "chroma"  # persistent vector database
COLLECTION = "docs"
ANSWER_CACHE_DIR = ROOT / "data" / "cache"  # answers to questions already asked
ANSWER_CACHE_TTL = int(os.getenv("ANSWER_CACHE_TTL", 24 * 60 * 60))  # seconds; 0 disables the cache

# Documentation sources.
MDN_REPO = "https://github.com/mdn/content.git"                  # JavaScript language (Array, Promise...)
NODE_DOCS_VERSION = os.getenv("NODE_DOCS_VERSION", "v24.21.0")  # Node.js runtime APIs (fs, http...)
PYTHON_DOCS_VERSION = os.getenv("PYTHON_DOCS_VERSION", "3.14")  # Python standard library

# Local models, served by Ollama.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "docs-rag-qwen2.5-3b")  # qwen2.5:3b, see ollama/Modelfile
LLM_TIMEOUT = 180     # seconds per LLM call, so a stuck generation cannot hang the app
LLM_MAX_TOKENS = 1024  # per LLM call; answers are ~100 words, this only stops runaway output
# Ollama unloads an idle model after 5 minutes, and loading it again takes seconds.
MODEL_KEEP_ALIVE = "30m"

# Limits on what goes into a record's text (characters), so a long page stays one readable chunk.
MAX_DESCRIPTION = 1500
MAX_NOTES = 600
MAX_CODE = 2500
