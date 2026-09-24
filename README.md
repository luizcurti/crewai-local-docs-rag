# Local Docs RAG with CrewAI

Ask questions about **JavaScript**, **Node.js** and **Python** functions, and get answers built from their official documentation: what the function is for, its parameters, and a real code example with its output.

![How a question is answered: the documentation is indexed once into a local vector database; each question goes through the answer cache, then a CrewAI Flow (understand, search functions and examples in parallel, build the context, write the answer with a local LLM), and the answer shows the documentation examples as documented.](docs/architecture.svg)

Everything runs on your machine. The documentation, the embeddings, the vector database and the LLM are all local: no API keys, no cloud calls, no telemetry.

```text
$ python flow.py "What is map used for?"

### JavaScript

`map()` creates a new array populated with the results of calling a provided function on each
element in the original array.

Example (Array.prototype.map): JavaScript Demo: Array.prototype.map()
    const array = [1, 4, 9, 16];
    const mapped = array.map((x) => x * 2);
    console.log(mapped);
Output:
    Array [2, 8, 18, 32]
Sources: Array.prototype.map (developer.mozilla.org)

### Python

`map()` creates an iterator that applies a function to every item of an iterable, yielding
the results...
    list(map(lambda x: x * 2, [1, 2, 3]))
Example written by the model: the official documentation has no example for this function.
Sources: map (docs.python.org)
```

`map` exists in both languages and the question names neither, so the answer has a section for each. The explanations are written by the LLM from the retrieved documentation; the examples and their output are copied from the documentation.

## Quick start

From a fresh clone, one command sets up everything and starts the web UI:

```bash
./start.sh --yes
```

It installs or downloads whatever is missing, then prints a link to the UI:

1. Checks for git and Python 3.12 or 3.13 (on macOS, offers to install Python with Homebrew).
2. Creates the Python environment and installs the packages, again whenever `requirements.txt` changes.
3. Installs Ollama if needed (Homebrew on macOS, the official script on Linux) and starts it.
4. Downloads the models: `nomic-embed-text` (~270 MB) and `qwen2.5:3b` (~1.9 GB).
5. Downloads the JavaScript, Node.js and Python documentation (~130 MB) and builds the vector database (8 to 15 minutes).
6. Loads the model into memory and starts the UI.

Without `--yes`, it asks before each download. Later runs skip what is already there and start in seconds. Ctrl+C stops the UI.

Requirements: macOS or Linux, about 3 GB of free disk space, and 8 GB of memory or more. Everything else is installed by the script.

## How it works

The diagram at the top shows the whole flow. The pieces:

| Layer         | Technology                                                           |
| ------------- | -------------------------------------------------------------------- |
| Documentation | MDN (JavaScript language), Node.js v24.21.0 API, Python 3.14 library |
| Embeddings    | `nomic-embed-text` via Ollama                                        |
| Vector store  | [ChromaDB](https://www.trychroma.com/), persistent, local            |
| Orchestration | [CrewAI](https://www.crewai.com/) Flow with one agent                |
| LLM           | `qwen2.5:3b` via Ollama                                              |
| UI            | [Streamlit](https://streamlit.io/)                                   |

### The documentation

JavaScript is covered by two sources: MDN documents the language (`Array.prototype.map`, `Promise`, `JSON.parse`), and the Node.js docs document the runtime (`fs`, `http`, `path`).

| Source     | Origin                                                 | Functions | Examples |
| ---------- | ------------------------------------------------------ | --------- | -------- |
| JavaScript | MDN JavaScript reference (`mdn/content`, sparse clone) | 1,140     | 2,737    |
| Node.js    | `nodejs.org/docs/v24.21.0/api/<module>.md`             | 3,650     | 1,703    |
| Python     | `docs.python.org/3.14` text and HTML archives          | 10,274    | 2,917    |

### One record per function, one per example

The documentation is not cut into fixed-size chunks. Each parser finds the API entries (functions, methods, classes, properties, events, statements, modules) and their code examples:

- Every entry becomes a **function record**: name, signature, description, parameters, return value, notes and source link.
- Every example becomes a separate **example record**: its code and expected output, linked to its function.

```text
ID: javascript_array_map                      ID: javascript_array_map_example_01

Array.prototype.map (method)                  Example: JavaScript Demo: Array.prototype.map()
Language: JavaScript (language reference)     Language: JavaScript (language reference, MDN)
Module: Array                                 Module: Array
Object: Array                                 Object: Array
Function: map                                 Function: Array.prototype.map
Signature: map(callbackFn)
           map(callbackFn, thisArg)           Code:
                                              const array = [1, 4, 9, 16];
Description:                                  const mapped = array.map((x) => x * 2);
The map() method of Array instances creates   console.log(mapped);
a new array populated with the results of
calling a provided function on every element  Expected output:
                                              Array [2, 8, 18, 32]
Parameters:
- callbackFn: A function to execute for ...   Source: https://developer.mozilla.org/...
- thisArg (optional): A value to use as this

Returns:
A new array with each element being the result of the callback function.
```

The metadata makes records filterable, and tells JavaScript's `map` from Python's:

```json
{"type": "function", "language": "javascript", "runtime": "ecmascript", "module": "Array",
 "object": "Array", "function": "map", "full_name": "Array.prototype.map", "kind": "method"}
{"type": "function", "language": "python", "runtime": "cpython", "module": "builtins",
 "object": "builtins", "function": "map", "full_name": "map", "kind": "function"}
```

How each source is parsed:

- **MDN:** each page is Markdown with a YAML header (`page-type: javascript-instance-method`) and fixed sections: intro, interactive demo, `Syntax`, `Parameters`, `Return value`, `Description`, and `Examples` with one sub-heading per example. MDN macros (`{{jsxref("Array")}}`) are expanded, and examples marked `example-bad` are skipped.
- **Node.js:** an API section's heading is a single code span (`` ### `fs.readFile(path[, options], callback)` ``), optionally prefixed with `Class:`, `Static method:` or `Event:`. Parameters come from its `* \`path\` {string}` list, and versions from a hidden YAML block. An example shown twice, as `mjs` and `cjs`, is kept once. Code in prose sections belongs to the closest entry above it, or to the module.
- **Python:** the plain-text export keeps the reStructuredText layout. An API entry is an unindented signature with an indented body, and class members are entries of their own (`TestCase.assertEqual`). Examples are indented blocks and `>>>` sessions. Element ids from the HTML archive give each entry its qualified name and an exact link.
- Output comments (`// Expected output: 42`, `// Prints: 42`) are moved out of the code into the example's output.

### Answering a question

The query is a [CrewAI Flow](https://docs.crewai.com/concepts/flows). Each step has one job. Only two can call the LLM: translating a question asked in another language, and writing the answer.

1. **Understand** (code): finds the language asked about ("in Python", "in node"), the function names (`map`, `Array.map`, `fs.readFile`) and the intent (explain, example, parameters, compare). A question in another language ("Para que serve map?") is first translated into English by the LLM, because the embedding model is English-only. Answers are always in English.
2. **Function search** and **example search**, in parallel:
   - **Exact names:** the records of every name the question mentions, scored by similarity to the question.
   - **Semantic search:** the nearest records in Chroma, for questions that name no function ("how do I read a file line by line in node").
3. **Build context** (code): picks, for each language, one function per name and its documentation examples.
   - A question that names a language gets only that language. Otherwise, every language with a close enough match gets its own section.
   - Case matters, as in JavaScript: `map` is `Array.prototype.map`, `Map` is the `Map` class.
   - Between near-equal matches, an entry with an official example wins.
   - Matches below a relevance threshold are ignored: "what is the weather today" gets "Nothing relevant was found in the documentation".
4. **Write answer:** the *Documentation writer* agent gets one task per language, each with only that language's documentation, and explains the function in about 100 words. The documentation examples are then appended exactly as documented, with their output and links. The model writes an example only when the documentation has none, and that example is labelled as written by the model.

### Performance

On an M1 Pro (16 GB), an answer takes about 3 to 10 seconds, almost all of it spent writing the explanation. Understanding the question, both searches and building the context take under a second together.

- **Streaming:** the UI shows each section while it is written, so the first words appear about a second after asking.
- **Answer cache:** a question asked again is answered from disk in milliseconds, with no LLM call. Answers are kept for a day. The cache key is the normalized question plus the model and the database version, so changing either one never serves a stale answer.
- **Tokens:** a one-language answer uses about 650 prompt and 110 completion tokens; a two-language answer about 1,050 and 230. The model reads the function records and only the titles and outputs of the examples, not their code. The UI shows the time and tokens of each answer, and the session total.
- **The model stays loaded** between questions for 30 minutes. Every LLM call has a timeout, and the answer length is capped.

## Usage

### Web UI

`./start.sh`, or `.venv/bin/streamlit run app.py`. Two tabs:

- **Ask:** type a question, or pick an example. The answer streams in, then appears next to how it was built: how the question was understood, the name and semantic matches with their scores, and the exact context sent to the LLM.
- **Vector database:** queries the records directly, without the LLM. Search by meaning or by exact name, filtered by record type and language.

### Terminal

```bash
.venv/bin/python flow.py "What parameters does map take?"
.venv/bin/python flow.py "Give me an example of Array.map in JavaScript"
.venv/bin/python flow.py --no-cache "What is map used for?"   # skip the answer cache
```

The last line shows the time, tokens and the records used:

```text
[6.9s | 1032 prompt + 232 completion tokens in 2 LLM calls | javascript: javascript_array_map (1 examples) | python: python_builtins_map (0 examples)]
```

### Manual setup

What `start.sh` does, step by step (Python 3.12 or 3.13, git and [Ollama](https://ollama.com) required):

```bash
# Models
brew install ollama && brew services start ollama   # Linux: see ollama.com
ollama pull nomic-embed-text
ollama pull qwen2.5:3b
ollama create docs-rag-qwen2.5-3b -f ollama/Modelfile   # 8k context, capped answer length

# Python environment
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Download the documentation and build the vector database (~22,400 records, 8 to 15 minutes)
.venv/bin/python ingest.py

# Check everything, then start the UI
.venv/bin/python preflight.py
.venv/bin/streamlit run app.py
```

### Other commands

```bash
.venv/bin/python ingest.py --sources python     # rebuild one source (mdn, node, python), keep the others
.venv/bin/python ingest.py --reset              # rebuild the whole database
.venv/bin/python answer_cache.py                # clear the answer cache (e.g. after changing the prompt)
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest   # tests; no Ollama or database needed
```

### Configuration

Environment variables:

| Variable              | Default               | Purpose                                                                 |
| --------------------- | --------------------- | ----------------------------------------------------------------------- |
| `LLM_MODEL`           | `docs-rag-qwen2.5-3b` | The Ollama model that writes answers. `ollama/Modelfile.7b` creates `docs-rag-qwen2.5` (qwen2.5:7b), slower and more careful. |
| `EMBED_MODEL`         | `nomic-embed-text`    | The embedding model. Changing it requires `ingest.py --reset`.          |
| `OLLAMA_URL`          | `http://localhost:11434` | Where Ollama runs.                                                   |
| `ANSWER_CACHE_TTL`    | `86400`               | How long answers are cached, in seconds. `0` disables the cache.        |
| `NODE_DOCS_VERSION`   | `v24.21.0`            | The Node.js docs to index.                                              |
| `PYTHON_DOCS_VERSION` | `3.14`                | The Python docs to index.                                               |
| `PORT`                | `8501`                | The web UI's port, for `start.sh`.                                      |

## Adding a language

Nothing outside `sources/` and `languages.py` is specific to JavaScript or Python. To add a language:

1. Write a source adapter, e.g. `sources/java.py`. It exposes `NAME`, `LABEL`, `RUNTIME`, `version()` and `load_all()`, which downloads the documentation and returns `ApiEntry` objects.
2. Register it in `sources/__init__.py`, and add its language and runtime to `languages.py`:
   ```python
   Language("java", "Java", "java", frozenset({"java"}))
   Runtime("jdk", "java", "Java SE API", "java")
   ```
3. Index it: `python ingest.py --sources java`.

Question analysis, record IDs, the per-language answer sections and the UI filters all read `languages.py`.

## Project structure

| File                | Purpose                                                                        |
| ------------------- | ------------------------------------------------------------------------------ |
| `start.sh`          | From a fresh clone to the running UI: installs, downloads and indexes what is missing. |
| `config.py`         | Paths, documentation versions, models, limits; disables telemetry.             |
| `languages.py`      | The languages and runtimes the system knows.                                   |
| `sources/mdn.py`    | Downloads and parses the MDN JavaScript reference.                             |
| `sources/node.py`   | Downloads and parses the Node.js API Markdown.                                 |
| `sources/python.py` | Downloads and parses the Python library docs.                                  |
| `entries.py`        | The `ApiEntry` / `CodeExample` model, record IDs, record text and metadata.    |
| `ingest.py`         | Parses the sources, embeds the records and stores them in ChromaDB.            |
| `store.py`          | Embeddings, the Chroma collection, semantic search and exact-name lookups.     |
| `query.py`          | Question analysis: language, function names, intent.                          |
| `flow.py`           | The CrewAI Flow, the writer agent, answer assembly, and the terminal command.  |
| `answer_cache.py`   | The answer cache.                                                              |
| `app.py`            | The Streamlit UI.                                                              |
| `preflight.py`      | Checks Ollama, the models and the vector database.                             |
| `ollama/`           | Modelfiles: context size and answer length cap.                                |
| `docs/architecture.svg` | The diagram at the top of this README.                                    |
| `tests/`            | Tests for the parsers, records, question analysis, ranking, answers, cache, vector lookups and UI. |

## Limitations

- **Not every function has an official example:** 98% of MDN entries do, 27% of Node.js entries and 13% of Python entries. For the others, the model writes the example, which is labelled and not executed.
- **Questions that name no function depend on semantic search**, which finds the right function less reliably than a name. For example, "create a new array by applying a function to every element" ranks `Array.prototype.map` 12th.
- **A small model:** `qwen2.5:3b` sometimes phrases things loosely. The documentation examples are unaffected, because they are copied, not generated.
- **One version per source:** changing `NODE_DOCS_VERSION` or `PYTHON_DOCS_VERSION` and re-running `ingest.py --sources <name>` replaces that source.
- **The answer cache matches wording, not meaning:** "What is map for?" and "What is map used for?" are answered separately.

## License and attribution

The documentation is downloaded by `ingest.py` and not redistributed here. MDN content is © Mozilla Contributors (CC-BY-SA 2.5, code samples CC0). The Node.js documentation is © OpenJS Foundation and contributors (MIT). The Python documentation is © Python Software Foundation (PSF License).
