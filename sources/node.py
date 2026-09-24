"""Node.js runtime APIs (fs, http, path...): one Markdown file per module, pinned to
NODE_DOCS_VERSION.

API sections have a heading made of one code span, optionally with a prefix:

    ### `fs.readFile(path[, options], callback)`
    ## Class: `FileHandle`
    ### Static method: `Buffer.from(array)`
    ### Event: `'close'`

followed by a hidden YAML block with the version history, a parameter list and the text:

    * `path` {string|Buffer|URL|integer} filename or file descriptor
    * `options` {Object|string}
      * `encoding` {string|null} **Default:** `null`
    * Returns: {Promise}

Every other heading ("Promises API", "Example: Read file stream line-by-Line") is prose:
its code blocks become examples of the closest API entry above it, or of the module.
"""

import re

import requests
import yaml

from config import MAX_DESCRIPTION, NODE_DOCS_VERSION, RAW_DIR
from entries import ApiEntry, CodeExample, split_output

NAME, LABEL, RUNTIME = "node", "Node.js", "nodejs"
BASE_URL = f"https://nodejs.org/docs/{NODE_DOCS_VERSION}/api"
CACHE_DIR = RAW_DIR / "node" / NODE_DOCS_VERSION

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
API_HEADING_RE = re.compile(r"^(?:(Class|Static method|Event|Static property):\s*)?`([^`]+)`$")
YAML_RE = re.compile(r"<!--\s*YAML\s*\n(.*?)-->", re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_RE = re.compile(r"^```(\w*)[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)
JS_FENCES = {"js", "mjs", "cjs", "javascript"}
VERSION_KEYS = {"added": "Added in", "deprecated": "Deprecated since", "removed": "Removed in"}


def version() -> str:
    return NODE_DOCS_VERSION


def list_modules() -> list[str]:
    names = re.findall(r"\]\(([a-z0-9_]+)\.md\)", _fetch("index"))
    return list(dict.fromkeys(names))


def load_all() -> list[ApiEntry]:
    entries = []
    for module in list_modules():
        entries += parse_module(module, _fetch(module))
    return entries


def _fetch(module: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{module}.md"
    if cached.exists():
        return cached.read_text()
    resp = requests.get(f"{BASE_URL}/{module}.md", timeout=60)
    resp.raise_for_status()
    cached.write_text(resp.text)
    return resp.text


def slugify(title: str) -> str:
    """Heading id used by the Node.js docs: 'fs.readFile(path[, options])' -> 'fsreadfilepath-options'."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def clean(text: str) -> str:
    """Markdown links to plain text: [`fs.stat()`][] and [text](url) -> the text."""
    text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text


def _history(raw: str) -> str:
    data = yaml.safe_load(raw) or {}
    lines = []
    for key, label in VERSION_KEYS.items():
        if data.get(key):
            value = data[key]
            lines.append(f"{label}: {', '.join(map(str, value)) if isinstance(value, list) else value}")
    return "\n".join(lines)


def _split(markdown: str) -> list[tuple[int, str, str]]:
    """[(level, raw heading, body)], ignoring '#' lines inside code blocks."""
    sections, level, title, body, in_fence = [], 0, "", [], False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            if title:
                sections.append((level, title, "\n".join(body)))
            level, title, body = len(match.group(1)), match.group(2).strip(), []
        else:
            body.append(line)
    if title:
        sections.append((level, title, "\n".join(body)))
    return sections


def parse_parameters(body: str) -> tuple[list[tuple[str, str]], str]:
    """The '* `name` {type} text' list at the top of an API section, and its 'Returns:' item.
    Nested items (options of an object) are folded into their parent's description."""
    params, returns, current = [], "", None
    for line in body.splitlines():
        top = re.match(r"^\* (.*)$", line)
        nested = re.match(r"^ {2,}\* (.*)$", line)
        if top:
            item = clean(top.group(1)).strip()
            if item.startswith("Returns:"):
                returns, current = item[len("Returns:"):].strip(), None
            else:
                m = re.match(r"`([^`]+)`\s*(.*)$", item)
                current = [m.group(1), m.group(2)] if m else [item, ""]
                params.append(current)
        elif nested and current:
            current[1] += ("; " if current[1] else "") + clean(nested.group(1)).replace("`", "").strip()
        elif current and line.startswith("  ") and line.strip():
            current[1] += " " + clean(line.strip())  # continuation line of the item
        elif line.strip() and not line.startswith(" "):
            current = None
    return [(n, " ".join(d.split())) for n, d in params], returns


def _body_parts(body: str) -> tuple[str, str, list[CodeExample]]:
    """(description, notes, examples) of a section body."""
    notes = []
    for m in YAML_RE.finditer(body):
        notes.append(_history(m.group(1)))
    body = COMMENT_RE.sub("", YAML_RE.sub("", body))

    examples, last_lang, prose_before = [], None, ""
    pos = 0
    for m in FENCE_RE.finditer(body):
        between = body[pos:m.start()]
        pos = m.end()
        text_before = [p.strip() for p in between.split("\n\n") if p.strip() and not p.strip().startswith("*")]
        if text_before:
            prose_before = " ".join(text_before[-1].split())
        lang = m.group(1)
        # The same example is usually shown twice, as ES module (mjs) and CommonJS (cjs).
        twin = lang == "cjs" and last_lang == "mjs" and not between.strip()
        last_lang = lang
        if lang in JS_FENCES and not twin:
            code, output = split_output(m.group(2).strip("\n"))
            examples.append(CodeExample(clean(prose_before).rstrip(":") or "", code, "js", output))

    prose = FENCE_RE.sub("\n\n\x00CODE\x00\n\n", body)
    paragraphs = []
    for p in prose.split("\n\n"):
        p = p.strip()
        if p == "\x00CODE\x00":
            if paragraphs and paragraphs[-1].endswith(":"):
                paragraphs.pop()  # "An example using the buffer option:" means nothing without its code
            continue
        if not p or p.startswith("* "):
            continue
        if p.startswith(">") and "Stability" in p:
            notes.append(" ".join(p.lstrip("> ").split()))
            continue
        paragraphs.append(" ".join(clean(p).split()))
    description = "\n\n".join(paragraphs)
    # Some sections (errors, CLI) are pages long; the record keeps MAX_DESCRIPTION characters
    # anyway, the rest is only trimmed here so memory stays small during ingestion.
    return description[: MAX_DESCRIPTION * 2], "\n".join(n for n in notes if n), examples


def _api(heading: str, module: str, owner: str | None) -> dict | None:
    """Name parts of an API heading, or None for a prose heading."""
    match = API_HEADING_RE.match(heading)
    if not match:
        return None
    prefix, code = match.group(1), match.group(2).strip()
    if code.startswith("-"):
        return None  # a command-line option (cli.md: `--env-file=file`), not an API
    if prefix == "Event":
        name = code.strip("'\"")
        return {"kind": "event", "object": owner or module, "name": name,
                "full_name": f"{owner or module} event '{name}'", "signature": ""}
    constructor = code.startswith("new ")
    code = code.removeprefix("new ")
    full_name = re.split(r"[(\s]", code, maxsplit=1)[0]
    parts = full_name.split(".")
    name = parts[-1]
    if prefix == "Class":
        return {"kind": "class", "object": name, "name": name, "full_name": full_name, "signature": ""}
    if constructor:
        kind = "constructor"
    elif "(" in code:
        kind = "static method" if prefix == "Static method" else (
            "function" if len(parts) == 1 or parts[0] == module or owner is None else "method")
    else:
        kind = "property"
    obj = owner if owner and len(parts) > 1 and parts[0] != module else (".".join(parts[:-1]) or module)
    return {"kind": kind, "object": obj, "name": name, "full_name": full_name, "signature": code}


def parse_module(module: str, markdown: str) -> list[ApiEntry]:
    url = f"{BASE_URL}/{module}.html"
    anchors: dict[str, int] = {}
    entries: list[ApiEntry] = []
    module_entry: ApiEntry | None = None
    stack: list[tuple[int, ApiEntry | None, str | None]] = []  # (level, API entry, class name)

    for level, heading, body in _split(markdown):
        title = heading.replace("`", "")
        slug = slugify(title)
        n = anchors.get(slug, 0)
        anchors[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}_{n}"
        stack = [s for s in stack if s[0] < level]
        owner = next((cls for _, _, cls in reversed(stack) if cls), None)
        description, notes, examples = _body_parts(body)

        if module_entry is None:  # the page title: the module itself
            module_entry = ApiEntry("javascript", "nodejs", module, module, module, module, "module", url,
                                    description=description, notes=notes, examples=examples)
            entries.append(module_entry)
            continue

        api = _api(heading, module, owner)
        if api is None:
            # Prose section: its examples belong to the closest API entry above it.
            parent = next((e for _, e, _ in reversed(stack) if e), module_entry)
            for ex in examples:
                ex.title = ex.title or title
            parent.examples += examples
            stack.append((level, None, None))
            continue

        params, returns = parse_parameters(COMMENT_RE.sub("", YAML_RE.sub("", body)))
        entry = ApiEntry(
            language="javascript", runtime="nodejs", module=module, object=api["object"], name=api["name"],
            full_name=api["full_name"], kind=api["kind"], url=f"{url}#{anchor}", signature=api["signature"],
            description=description, parameters=params, returns=returns, notes=notes,
        )
        for ex in examples:
            ex.title = ex.title or f"{api['full_name']} example"
        entry.examples = examples
        entries.append(entry)
        stack.append((level, entry, api["name"] if api["kind"] == "class" else None))
    return entries
