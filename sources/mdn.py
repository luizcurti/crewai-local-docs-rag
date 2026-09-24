"""JavaScript language reference from MDN (Array.prototype.map, Promise, for...of...).

The Node.js docs only cover the runtime (fs, http...): the language itself is documented
by MDN. MDN publishes its pages as Markdown in github.com/mdn/content, one index.md per
page, with a YAML header (title, slug, page-type) and fixed sections:

    intro paragraph + interactive example (with "// Expected output:" comments)
    ## Syntax / ### Parameters / ### Return value
    ## Description
    ## Examples / ### <one heading per example>
"""

import re
import subprocess

import yaml

from config import MDN_REPO, RAW_DIR
from entries import ApiEntry, CodeExample, split_output

NAME, LABEL, RUNTIME = "mdn", "JavaScript (MDN)", "ecmascript"
REPO_DIR = RAW_DIR / "mdn" / "content"
REFERENCE = "files/en-us/web/javascript/reference"
SECTIONS = ["global_objects", "statements", "operators", "functions", "classes"]
BASE_URL = "https://developer.mozilla.org/en-US/docs/"

KINDS = {
    "javascript-instance-method": "method",
    "javascript-static-method": "static method",
    "javascript-function": "function",
    "javascript-constructor": "constructor",
    "javascript-class": "class",
    "javascript-namespace": "namespace",
    "javascript-instance-accessor-property": "property",
    "javascript-instance-data-property": "property",
    "javascript-static-accessor-property": "static property",
    "javascript-static-data-property": "static property",
    "javascript-global-property": "property",
    "javascript-operator": "operator",
    "javascript-statement": "statement",
    "javascript-language-feature": "language feature",
}
JS_FENCES = {"js", "javascript", "js-nolint", "mjs"}

MACRO_RE = re.compile(r"\{\{\s*([\w-]+)\s*(?:\((.*?)\))?\s*\}\}")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
FENCE_RE = re.compile(r"^```([^\n]*)\n(.*?)^```", re.DOTALL | re.MULTILINE)


def download() -> None:
    """Sparse, shallow clone: only the JavaScript reference (~12 MB), not all of MDN."""
    if REPO_DIR.exists():
        return
    REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", MDN_REPO, str(REPO_DIR)], check=True)
    subprocess.run(["git", "-C", str(REPO_DIR), "sparse-checkout", "set", REFERENCE], check=True)


def version() -> str:
    return subprocess.run(["git", "-C", str(REPO_DIR), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def load_all() -> list[ApiEntry]:
    download()
    entries = []
    for section in SECTIONS:
        for path in sorted((REPO_DIR / REFERENCE / section).rglob("index.md")):
            entry = parse_page(path.read_text())
            if entry:
                entries.append(entry)
    return entries


# ------------------------------------------------------------------ markdown cleanup

def _macro(match: re.Match) -> str:
    name, args = match.group(1).lower(), match.group(2)
    if name == "optional_inline":
        return "(optional)"
    if name == "deprecated_inline":
        return "(deprecated)"
    if not args or name.endswith(("sidebar", "header")) or name in {"interactiveexample", "embedlivesample", "compat", "specifications"}:
        return ""
    values = re.findall(r'"([^"]*)"|\'([^\']*)\'', args)
    values = [a or b for a, b in values]
    if not values:
        return ""
    # jsxref("Array/forEach", "forEach()") shows its second argument; with one argument,
    # the page path reads as a name: "Array/forEach" -> "Array.forEach".
    text = values[1] if len(values) > 1 and values[1] else values[0].replace("/", ".")
    return f"`{text}`" if name == "jsxref" and not text.startswith("`") else text


def clean(text: str) -> str:
    text = MACRO_RE.sub(_macro, text)
    text = LINK_RE.sub(r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _prose(text: str) -> str:
    """Paragraphs without code blocks, joined into plain text."""
    text = FENCE_RE.sub("", text)
    paragraphs = [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]
    return "\n\n".join(paragraphs)


def _sections(body: str, level: str) -> list[tuple[str, str]]:
    """Splits markdown on headings of one level: [(title, content)], the text before the
    first heading gets the title ""."""
    parts = re.split(rf"^{level} +(.+)$", body, flags=re.MULTILINE)
    out = [("", parts[0])]
    out += [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    return out


def parse_parameters(text: str) -> list[tuple[str, str]]:
    """Top-level items of an MDN definition list:
        - `callbackFn`
          - : A function to execute for each element..."""
    params, name, desc = [], None, []
    for line in text.splitlines():
        top = re.match(r"^- (.+)$", line)
        if top:
            if name:
                params.append((name, " ".join(desc)))
            name, desc = top.group(1).replace("`", "").strip(), []
        elif name and re.match(r"^  - : ", line):
            desc.append(line[6:].strip())
        elif name and desc and line.startswith("    ") and not line.strip().startswith("-"):
            desc.append(line.strip())
    if name:
        params.append((name, " ".join(desc)))
    return params


def _names(slug: str, title: str) -> tuple[str, str, str]:
    """(object, name, full_name) from the page slug and title.
    Global_Objects/Array/map -> ("Array", "map", "Array.prototype.map")
    Global_Objects/parseInt   -> ("globalThis", "parseInt", "parseInt")
    Statements/for...of       -> ("statements", "for...of", "for...of")"""
    parts = slug.split("/")[3:]  # drop Web/JavaScript/Reference
    full_name = re.sub(r"\(\)$", "", title.strip())
    if parts[0] != "Global_Objects":
        return parts[0].lower(), full_name, full_name
    if len(parts) == 2:
        return ("globalThis" if title.endswith("()") else parts[1]), parts[1], full_name
    return ".".join(parts[1:-1]), parts[-1], full_name


def parse_page(markdown: str) -> ApiEntry | None:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", markdown, re.DOTALL)
    if not match:
        return None
    meta, body = yaml.safe_load(match.group(1)), match.group(2)
    kind = KINDS.get(meta.get("page-type", ""))
    if not kind:
        return None  # errors, guides and landing pages are not API entries
    obj, name, full_name = _names(meta["slug"], meta["title"])

    sections = dict((t.lower(), c) for t, c in _sections(body, "##"))
    intro = sections.get("", "")
    examples = []

    # The interactive demo at the top of most pages is the shortest complete example.
    demo = re.search(r"\{\{\s*InteractiveExample\(\"([^\"]*)\".*?\n```js[^\n]*\n(.*?)^```", intro, re.DOTALL | re.MULTILINE)
    if demo:
        code, output = split_output(demo.group(2))
        examples.append(CodeExample(clean(demo.group(1)), code, "js", output))

    syntax = sections.get("syntax", "")
    signature = next((m.group(2).strip() for m in FENCE_RE.finditer(syntax)), "")
    sub = dict((t.lower(), c) for t, c in _sections(syntax, "###"))

    for title, content in _sections(sections.get("examples", ""), "###"):
        blocks = [
            m.group(2).strip("\n") for m in FENCE_RE.finditer(content)
            if m.group(1).split()[:1] and m.group(1).split()[0] in JS_FENCES and "example-bad" not in m.group(1)
        ]
        if blocks:
            code, output = split_output("\n\n".join(blocks))
            examples.append(CodeExample(clean(title) or f"{full_name} example", code, "js", output))

    return ApiEntry(
        language="javascript",
        runtime="ecmascript",
        module=obj if obj not in ("globalThis",) else "globals",
        object=obj,
        name=name,
        full_name=full_name,
        kind=kind,
        url=BASE_URL + meta["slug"],
        signature=clean(signature),
        description=_prose(clean(re.sub(r"\{\{\s*InteractiveExample.*", "", intro, flags=re.DOTALL))),
        parameters=[(clean(n), clean(d)) for n, d in parse_parameters(sub.get("parameters", ""))],
        returns=_prose(clean(sub.get("return value", ""))),
        notes=_prose(clean(sections.get("description", ""))),
        examples=examples,
    )
