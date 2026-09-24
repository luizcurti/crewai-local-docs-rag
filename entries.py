"""The unit of knowledge: one API entry (function, method, class...) and its code examples.

Every source parser (sources/) produces ApiEntry objects. Each entry becomes one
"function" chunk, and each of its examples becomes a separate "example" chunk that points
back to it, so the index can answer both "what is map for?" and "give me a map example".
"""

import re
from dataclasses import dataclass, field

from config import MAX_CODE, MAX_DESCRIPTION, MAX_NOTES
from languages import RUNTIMES, describe
# Examples show their output below the code: "// Expected output: 42", "# Prints: 42".
# Also at the end of a line of code: "console.log(x); // Prints: 42".
OUTPUT_COMMENT_RE = re.compile(r"^(.*?)[ \t]*(?://|#)\s*(?:expected output|prints|logs|output)\s*:\s?(.*)$", re.IGNORECASE)


@dataclass
class CodeExample:
    title: str   # what the example shows, e.g. "Mapping an array of numbers to square roots"
    code: str
    lang: str    # code fence language, e.g. "js" or "python"
    output: str = ""


@dataclass
class ApiEntry:
    language: str   # a key of languages.LANGUAGES: "javascript", "python"
    runtime: str    # a key of languages.RUNTIMES: "ecmascript" (MDN), "nodejs", "cpython"
    module: str     # "Array", "fs", "builtins", "pathlib"
    object: str     # what the function belongs to: "Array", "fs", "FileHandle", "str"
    name: str       # "map", "readFile", "split"
    full_name: str  # "Array.prototype.map", "fs.readFile", "str.split"
    kind: str       # "method", "function", "class", "property", "event", "statement", "module"...
    url: str
    signature: str = ""
    description: str = ""
    parameters: list[tuple[str, str]] = field(default_factory=list)
    returns: str = ""
    notes: str = ""
    examples: list[CodeExample] = field(default_factory=list)
    id: str = ""    # assigned by assign_ids()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def assign_ids(entries: list[ApiEntry]) -> None:
    """IDs like javascript_array_map, nodejs_fs_readfile, python_builtins_map. Overloads
    (Buffer.from(array), Buffer.from(string)...) get a _2, _3... suffix."""
    seen: dict[str, int] = {}
    for e in entries:
        prefix = RUNTIMES[e.runtime].id_prefix
        parts = [prefix] + ([e.object] if e.object != e.name else []) + [e.name]
        base = "_".join(p for p in (slug(x) for x in parts) if p) or prefix
        seen[base] = seen.get(base, 0) + 1
        e.id = base if seen[base] == 1 else f"{base}_{seen[base]}"


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + " [...]"


def short_title(text: str, limit: int = 120) -> str:
    """An example title from the sentence that introduced it: first sentence, no list
    marker, no trailing colon, at most `limit` characters."""
    text = re.sub(r"^[*\-]\s+", "", " ".join(text.split()))
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].rstrip(":. ")
    return first if len(first) <= limit else truncate(first, limit)


def split_output(code: str) -> tuple[str, str]:
    """Moves "// Expected output: ..." comments out of the code and returns (code, output)."""
    lines, outputs = [], []
    for line in code.splitlines():
        match = OUTPUT_COMMENT_RE.match(line)
        if not match:
            lines.append(line)
            continue
        outputs.append(match.group(2).strip())
        if match.group(1).strip():
            lines.append(match.group(1))  # keep the code, drop the comment
    code = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    return code, "\n".join(o for o in outputs if o)


def function_text(e: ApiEntry) -> str:
    lines = [
        f"{e.full_name} ({e.kind})",
        f"Language: {describe(e.language, e.runtime)}",
        f"Module: {e.module}",
        f"Object: {e.object}",
        f"Function: {e.name}",
    ]
    if e.signature:
        lines.append(f"Signature: {e.signature}")
    lines += ["", "Description:", truncate(e.description, MAX_DESCRIPTION) or "(none)"]
    if e.parameters:
        lines += ["", "Parameters:"] + [f"- {n}: {d}" if d else f"- {n}" for n, d in e.parameters]
    if e.returns:
        lines += ["", "Returns:", e.returns]
    if e.notes:
        lines += ["", "Notes:", truncate(e.notes, MAX_NOTES)]
    lines += ["", f"Source: {e.url}"]
    return "\n".join(lines)


def example_text(e: ApiEntry, ex: CodeExample) -> str:
    lines = [
        f"Example: {short_title(ex.title)}",
        f"Language: {describe(e.language, e.runtime)}",
        f"Module: {e.module}",
        f"Object: {e.object}",
        f"Function: {e.full_name}",
        "",
        "Code:",
        truncate(ex.code, MAX_CODE) if len(ex.code) > MAX_CODE else ex.code,
    ]
    if ex.output:
        lines += ["", "Expected output:", ex.output]
    lines += ["", f"Source: {e.url}"]
    return "\n".join(lines)


def metadata(e: ApiEntry) -> dict:
    return {
        "language": e.language,
        "runtime": e.runtime,
        "module": e.module,
        "object": e.object,
        "function": e.name,
        "full_name": e.full_name,
        "kind": e.kind,
        "url": e.url,
        "source": "official documentation",
        # Lowercase copies for exact-name lookups ("map", "array.prototype.map").
        "name_lower": e.name.lower(),
        "full_name_lower": e.full_name.lower(),
        "object_lower": e.object.lower(),
    }


def to_chunks(e: ApiEntry) -> list[dict]:
    """One function chunk plus one example chunk per example."""
    meta = metadata(e)
    chunks = [{
        "id": e.id,
        "text": function_text(e),
        # "examples" counts them: search prefers, between near-equal matches, an entry that has one.
        "metadata": {**meta, "type": "function", "signature": e.signature[:300], "examples": len(e.examples)},
    }]
    for i, ex in enumerate(e.examples, 1):
        chunks.append({
            "id": f"{e.id}_example_{i:02d}",
            "text": example_text(e, ex),
            # The code and output are kept as documented, to be shown verbatim in answers.
            "metadata": {
                **meta, "type": "example", "function_id": e.id, "example_number": i,
                "title": short_title(ex.title), "lang": ex.lang, "code": ex.code[:MAX_CODE], "output": ex.output[:1000],
            },
        })
    return chunks
