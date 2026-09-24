#!/usr/bin/env bash
# Sets up everything that is missing and starts the web UI. From a fresh clone:
#
#   ./start.sh          # asks before each download
#   ./start.sh --yes    # answers yes to everything: one command from zero to the UI
#   PORT=8502 ./start.sh
#
# Steps: git and Python 3.12-3.13 -> Python environment -> Ollama -> models ->
#        documentation + vector database -> web UI.
# The first run downloads about 2.5 GB (models, documentation) and indexes the
# documentation (8 to 15 minutes). Later runs start in seconds.
# Ctrl+C stops the UI (Ollama keeps running).

set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8501}"
URL="http://localhost:${PORT}"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
PY=.venv/bin/python
LOG=data/streamlit.log
YES=0

for arg in "$@"; do
  case "$arg" in
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see ./start.sh --help)" >&2; exit 2 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
step() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }
confirm() {
  if [[ "$YES" == 1 ]]; then echo "$1 yes (--yes)"; return 0; fi
  read -r -p "$1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}
link() { printf '\033]8;;%s\033\\%s\033]8;;\033\\\n' "$1" "$1"; }  # clickable in most terminals
ollama_up() { curl -sf "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; }
ui_up() { curl -sf "${URL}/_stcore/health" >/dev/null 2>&1; }
is_macos() { [[ "$(uname)" == "Darwin" ]]; }
has() { command -v "$1" >/dev/null 2>&1; }

show_link() {
  echo
  bold "Local Docs RAG is running:"
  printf '    '; link "$URL"
  echo
}

# Already running? Just show the link.
if ui_up; then
  show_link
  echo "(It was already running. Stop it with: pkill -f 'streamlit run app.py')"
  exit 0
fi

# 1. git (MDN is downloaded with a sparse git clone)
has git || fail "git is required. Install it (macOS: xcode-select --install) and run ./start.sh again."

# 2. Python 3.12 or 3.13 (numpy needs 3.12+, CrewAI does not support 3.14 yet)
supported() { "$1" -c 'import sys; sys.exit(not (3, 12) <= sys.version_info[:2] <= (3, 13))' 2>/dev/null; }
if [[ ! -x "$PY" ]]; then
  PYTHON=""
  for candidate in python3.13 python3.12 python3; do
    if has "$candidate" && supported "$candidate"; then PYTHON="$candidate"; break; fi
  done
  if [[ -z "$PYTHON" ]]; then
    if is_macos && has brew && confirm "Python 3.12 or 3.13 is required. Install Python 3.13 with Homebrew?"; then
      brew install python@3.13
      PYTHON="$(brew --prefix)/bin/python3.13"
    else
      fail "Python 3.12 or 3.13 is required (found: $(python3 --version 2>&1 || echo none)). See https://www.python.org/downloads/"
    fi
  fi
  step "Creating the Python environment with $("$PYTHON" --version)"
  "$PYTHON" -m venv .venv
fi
supported "$PY" || fail ".venv uses $("$PY" --version); Python 3.12 or 3.13 is required. Delete .venv and run ./start.sh again."

# 3. Python packages, installed again whenever requirements.txt changes
REQ_HASH="$(shasum requirements.txt | cut -d' ' -f1)"
if [[ "$(cat .venv/.requirements-hash 2>/dev/null)" != "$REQ_HASH" ]]; then
  step "Installing the Python packages (requirements.txt)"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt
  echo "$REQ_HASH" > .venv/.requirements-hash
fi

# 4. Ollama: installed and running
if ! has ollama; then
  if is_macos && has brew; then
    confirm "Ollama is not installed. Install it with Homebrew?" || fail "Install Ollama from https://ollama.com/download"
    brew install ollama
  elif ! is_macos; then
    confirm "Ollama is not installed. Install it with the official script (https://ollama.com/install.sh)?" \
      || fail "Install Ollama from https://ollama.com/download"
    curl -fsSL https://ollama.com/install.sh | sh
  else
    fail "Ollama is not installed. Download it from https://ollama.com/download, then run ./start.sh again."
  fi
fi
if ! ollama_up; then
  step "Starting Ollama"
  if has brew && brew services list 2>/dev/null | grep -q '^ollama'; then
    brew services start ollama >/dev/null
  else
    mkdir -p data && nohup ollama serve >data/ollama.log 2>&1 &
  fi
  for _ in $(seq 30); do ollama_up && break; sleep 1; done
  ollama_up || fail "Ollama did not start. Try: ollama serve"
fi

# 5. Models
read -r LLM_MODEL EMBED_MODEL < <("$PY" -c "import config; print(config.LLM_MODEL, config.EMBED_MODEL)")
installed=$(ollama list | awk 'NR>1 {sub(":latest", "", $1); print $1}')
if ! grep -qx "$EMBED_MODEL" <<<"$installed"; then
  confirm "Download the embedding model '$EMBED_MODEL' (~270 MB)?" || fail "Run: ollama pull $EMBED_MODEL"
  ollama pull "$EMBED_MODEL"
fi
if ! grep -qx "$LLM_MODEL" <<<"$installed"; then
  if [[ "$LLM_MODEL" == "docs-rag-qwen2.5-3b" ]]; then
    confirm "Download the LLM qwen2.5:3b (~1.9 GB) and create '$LLM_MODEL'?" \
      || fail "Run: ollama pull qwen2.5:3b && ollama create $LLM_MODEL -f ollama/Modelfile"
    ollama pull qwen2.5:3b
    ollama create "$LLM_MODEL" -f ollama/Modelfile
  else
    fail "The LLM '$LLM_MODEL' is missing. See ollama/Modelfile.7b, or run: ollama pull $LLM_MODEL"
  fi
fi

# 6. Documentation and vector database
records=$("$PY" -c "from store import get_collection; print(get_collection().count())" 2>/dev/null || echo 0)
if [[ "$records" == "0" ]]; then
  confirm "Download the JavaScript, Node.js and Python documentation (~130 MB) and build the vector database (8 to 15 minutes)?" \
    || fail "Run: $PY ingest.py"
  "$PY" ingest.py
fi

# 7. Web UI
step "Loading the model into memory"
"$PY" -c "from flow import keep_model_loaded; from store import embed_query; keep_model_loaded(); embed_query('warm up')" >/dev/null 2>&1 || true

step "Starting the web UI"
mkdir -p data
.venv/bin/streamlit run app.py --server.headless true --server.port "$PORT" >"$LOG" 2>&1 &
UI_PID=$!
trap 'echo; step "Stopping the web UI"; kill "$UI_PID" 2>/dev/null; wait "$UI_PID" 2>/dev/null; exit 0' INT TERM

for _ in $(seq 60); do
  ui_up && break
  kill -0 "$UI_PID" 2>/dev/null || fail "The web UI stopped. See $LOG"
  sleep 1
done
ui_up || fail "The web UI did not start. See $LOG"

show_link
echo "Press Ctrl+C to stop. Log: $LOG"
wait "$UI_PID"
