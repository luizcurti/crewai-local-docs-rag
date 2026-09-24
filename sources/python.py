"""Python standard library, from the official plain-text archive of docs.python.org.

The text export keeps the reStructuredText layout:
- headings are a line underlined (and sometimes overlined) with a punctuation character,
  and the level comes from the order in which each character first appears in the file;
- API entries are an unindented signature line followed by an indented body, e.g.
  "map(function, iterable, /, *iterables, strict=False)". Members documented inside a
  class ("   assertEqual(first, second, msg=None)") are entries of their own;
- code examples are indented blocks, often ">>>" sessions, introduced by a line ending
  with ":" ("For example:").
"""

import io
import re
import textwrap
import zipfile
from dataclasses import dataclass, field

import requests

from config import PYTHON_DOCS_VERSION, RAW_DIR
from entries import ApiEntry, CodeExample, split_output

NAME, LABEL, RUNTIME = "python", "Python", "cpython"
BASE_URL = f"https://docs.python.org/{PYTHON_DOCS_VERSION}"
ARCHIVE_URL = f"{BASE_URL}/archives/python-{PYTHON_DOCS_VERSION}-docs-text.zip"
# The HTML archive is only used for its element ids: they give each entry its fully
# qualified name (pathlib.PurePath.with_name) and a link that points at it.
HTML_ARCHIVE_URL = f"{BASE_URL}/archives/python-{PYTHON_DOCS_VERSION}-docs-html.zip"
CACHE_DIR = RAW_DIR / "python" / PYTHON_DOCS_VERSION
BUILTIN_PAGES = {"functions", "stdtypes", "exceptions", "constants"}

ADORNMENT_RE = re.compile(r"^([=\-`:'\"~^_*+#<>.])\1{3,}\s*$")
SIGNATURE_RE = re.compile(
    r"^(?:(?:class|exception|classmethod|staticmethod|async|abstractmethod|"
    r"coroutine|awaitable|await)\s+)*"
    r"@?"                       # decorators, e.g. @functools.lru_cache(maxsize=128)
    r"[A-Za-z_][\w.]*"          # dotted name
    r"(?:\[[^\]]*\])?"          # optional type parameters, e.g. list[T]
    r"(?:\(.*\))?"              # optional argument list
    r"(?:\s*->\s*\S.*)?$"       # optional return annotation
)
API_KEYWORDS_RE = re.compile(
    r"^(?:(?:class|exception|classmethod|staticmethod|async|abstractmethod|coroutine|"
    r"awaitable|await)\s+)*@?"
)
ADMONITIONS = ("Note:", "Warning:", "See also:", "Caution:", "Important:", "Tip:", "Attention:", "Hint:", "Danger:")
GENERIC_INTROS = {"for example:", "example:", "examples:", "for instance:", "example usage:"}


@dataclass
class Section:
    path: list[str]  # heading path; API entries end with their signature
    body: str
    anchor: str | None = None
    overloads: list[str] = field(default_factory=list)  # more signatures stacked below the first


def version() -> str:
    return PYTHON_DOCS_VERSION


def load_all() -> list[ApiEntry]:
    entries = []
    for path in _text_pages():
        folder, ids = _html_page(path.stem)
        entries += parse_page(path.stem, path.read_text(), ids, folder)
    return entries


def _text_pages():
    """Library pages. Python 3.14 moved the built-ins pages (functions, stdtypes...) from
    library/ to builtins/, so both folders are read."""
    root = _extract()
    pages = {p.stem: p for folder in ("library", "builtins") for p in sorted((root / folder).glob("*.txt"))}
    return list(pages.values())


# ------------------------------------------------------------------ download

def _extract():
    if not CACHE_DIR.exists():
        resp = requests.get(ARCHIVE_URL, timeout=300)
        resp.raise_for_status()
        CACHE_DIR.mkdir(parents=True)
        zipfile.ZipFile(io.BytesIO(resp.content)).extractall(CACHE_DIR)
    return CACHE_DIR / f"python-{PYTHON_DOCS_VERSION}-docs-text"


def _html_page(stem: str) -> tuple[str, set[str]]:
    """(folder the page is published in, its element ids). Pages that only redirect
    (library/functions.html -> builtins/functions.html) are skipped."""
    root = CACHE_DIR / f"python-{PYTHON_DOCS_VERSION}-docs-html"
    if not root.exists():
        resp = requests.get(HTML_ARCHIVE_URL, timeout=600)
        resp.raise_for_status()
        zipfile.ZipFile(io.BytesIO(resp.content)).extractall(CACHE_DIR)
    for folder in ("builtins", "library"):
        page = root / folder / f"{stem}.html"
        if page.exists():
            html = page.read_text()
            if "You should have been redirected" not in html:
                return folder, set(re.findall(r'id="([^"]+)"', html))
    return "library", set()


# ------------------------------------------------------------------ sections

def _api_name(signature: str) -> str:
    """'classmethod Path.from_uri(uri)' -> 'Path.from_uri'."""
    return re.split(r"[(\[\s]", API_KEYWORDS_RE.sub("", signature), maxsplit=1)[0]


def _heading_id(title: str) -> str:
    """docutils section id: '5.1. More on Lists' -> 'more-on-lists'."""
    title = re.sub(r"^\d+(\.\d+)*\.\s*", "", title)
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _is_signature(line: str) -> bool:
    if not line or line[0].isspace() or not SIGNATURE_RE.match(line):
        return False
    # Plain words ("Example") are not API entries; require a call, attribute or keyword.
    return "(" in line or "." in line or " " in line


MEMBER_INDENT = "   "  # members of a class are indented by three spaces inside it
MEMBER_BODY_INDENT = "      "


def _is_member_signature(line: str) -> bool:
    """An API entry nested in a class, e.g. '   assertEqual(first, second, msg=None)'."""
    if not line.startswith(MEMBER_INDENT) or line.startswith(MEMBER_INDENT + " "):
        return False
    return bool(SIGNATURE_RE.match(line.strip()))


def _qualify(member: str, owner: str) -> str:
    """'assertEqual(first, ...)' in 'class unittest.TestCase(...)' -> 'TestCase.assertEqual(first, ...)',
    the way the docs write top-level methods (PurePath.with_name)."""
    keywords = API_KEYWORDS_RE.match(member).group(0)
    rest = member[len(keywords):]
    if "." in re.split(r"[(\[\s]", rest, maxsplit=1)[0]:
        return member  # already qualified
    return f"{keywords}{_api_name(owner).split('.')[-1]}.{rest}"


def _next_content(lines: list[str], i: int) -> str:
    for line in lines[i:]:
        if line.strip():
            return line
    return ""


def split_sections(text: str) -> list[Section]:
    lines = text.splitlines()
    levels: list[str] = []  # adornment characters, in order of first appearance
    stack: list[str] = []   # current heading path
    api: str | None = None     # current API entry under the heading path
    member: str | None = None  # current entry nested in that API entry (a class method)
    body: list[str] = []
    overloads: list[str] = []
    sections = []

    def flush():
        content = textwrap.dedent("\n".join(body)).strip("\n")
        path = stack + ([api] if api else []) + ([member] if member else [])
        if path and (content.strip() or api):
            sections.append(Section(path, content, overloads=list(overloads)))

    i = 0
    while i < len(lines):
        line = lines[i]
        prev = lines[i - 1] if i else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        stripped = line.strip()

        # Heading: text line followed by an adornment line at least as long.
        if (
            stripped
            and not line[0].isspace()
            and ADORNMENT_RE.match(nxt)
            and len(nxt.strip()) >= len(stripped)
            and (not prev.strip() or ADORNMENT_RE.match(prev))
        ):
            flush()
            char = nxt.strip()[0]
            if char not in levels:
                levels.append(char)
            stack = stack[: levels.index(char)] + [stripped.replace('"', "")]
            api, member, body, overloads = None, None, [], []
            i += 2
            continue

        # Overlines and transitions ("=====" on its own) carry no content.
        if ADORNMENT_RE.match(line):
            i += 1
            continue

        # API entry: signature line whose body is indented (or another stacked signature).
        if _is_signature(line) and not prev.strip():
            following = _next_content(lines, i + 1)
            if following.startswith("   ") or _is_signature(following):
                flush()
                api, member, body, overloads = stripped, None, [], []
                i += 1
                # Overloaded signatures stacked right below belong to the same entry.
                while i < len(lines) and _is_signature(lines[i]):
                    overloads.append(lines[i].strip())
                    i += 1
                continue

        # A member of the current API entry: an indented signature whose own body is
        # indented once more. Each member becomes its own section.
        if api and _is_member_signature(line) and not prev.strip():
            following = _next_content(lines, i + 1)
            if following.startswith(MEMBER_BODY_INDENT) or _is_member_signature(following):
                flush()
                member, body, overloads = _qualify(stripped, api), [], []
                i += 1
                while i < len(lines) and _is_member_signature(lines[i]):
                    overloads.append(_qualify(lines[i].strip(), api))
                    i += 1
                continue

        # Prose back at the class's indentation ends the member.
        if member and stripped and not line.startswith(MEMBER_BODY_INDENT):
            flush()
            member, body, overloads = None, [], []

        # Unindented prose after an API entry goes back to the enclosing section.
        if api and stripped and not line[0].isspace():
            flush()
            api, member, body, overloads = None, None, [], []

        body.append(line)
        i += 1

    flush()
    return sections


def add_anchors(sections: list[Section], ids: set[str]) -> None:
    """Only ids that exist in the published HTML are used, so a link is never broken."""
    for sec in sections:
        if len(sec.path) == 1:
            continue  # page introduction: the plain page URL
        title = sec.path[-1]
        if _is_signature(title) or _is_member_signature("   " + title):
            name = _api_name(title)
            # Sphinx ids are fully qualified: 'PurePath.with_name' -> 'pathlib.PurePath.with_name'.
            matches = sorted((i for i in ids if i == name or i.endswith("." + name)), key=len)
            sec.anchor = matches[0] if matches else None
        else:
            candidate = _heading_id(title)
            sec.anchor = candidate if candidate in ids else None


# ------------------------------------------------------------------ entries

def split_blocks(body: str) -> list[tuple[str, str]]:
    """[("text" | "code", content)]: code blocks are indented blocks (blank lines inside
    them do not end them) and ">>>" sessions."""
    blocks: list[tuple[str, list[str]]] = []
    after_blank = False
    for line in body.splitlines():
        if not line.strip():
            after_blank = True
            continue
        indented = line.startswith("   ")
        current = blocks[-1] if blocks else None
        # Output lines of a ">>>" session are not indented but belong to it.
        in_session = current and current[0] == "code" and current[1][0].lstrip().startswith(">>>") and not after_blank
        kind = "code" if indented or line.startswith(">>>") or in_session else "text"
        if current and current[0] == kind and (not after_blank or (kind == "code" and indented)):
            current[1].extend([""] * after_blank + [line])
        else:
            blocks.append((kind, [line]))
        after_blank = False
    return [(k, textwrap.dedent("\n".join(ls)).strip("\n")) for k, ls in blocks]


def parse_parameters(signature: str) -> list[tuple[str, str]]:
    """'map(function, iterable, /, *iterables, strict=False)' -> function, iterable, *iterables, strict=False."""
    match = re.search(r"\((.*)\)", signature)
    if not match:
        return []
    params, depth, current = [], 0, ""
    for ch in match.group(1):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            params.append(current.strip())
            current = ""
        else:
            current += ch
    params.append(current.strip())
    return [(p, "") for p in params if p and p not in ("/", "*")]


def _page_module(stem: str, title: str) -> str | None:
    if stem in BUILTIN_PAGES:
        return "builtins"
    match = re.match(r"^([\w.]+) --- ", title)
    return match.group(1) if match else None


def _entry_parts(body: str, qualified: str) -> tuple[str, str, list[CodeExample]]:
    description, notes, examples, previous = [], [], [], ""
    for kind, content in split_blocks(body):
        if kind == "code":
            is_session = content.startswith(">>>")
            if is_session or (previous.endswith(":") and not previous.startswith(ADMONITIONS)):
                title = previous if previous and previous.lower() not in GENERIC_INTROS else f"{qualified} example"
                code, output = (content, "") if is_session else split_output(content)
                examples.append(CodeExample(title.rstrip(":"), code, "python", output))
                if description and description[-1] == previous and previous.endswith(":"):
                    description.pop()  # "For example:" means nothing without its code
            elif previous.startswith(ADMONITIONS):
                notes.append(f"{previous} {' '.join(content.split())}")
            continue
        text = " ".join(content.split())
        previous = text
        if re.match(r"^(Added in version|Changed in version|Deprecated since|Availability)", text):
            notes.append(text)
        elif not text.startswith(ADMONITIONS):
            description.append(text)
    return "\n\n".join(description), "\n".join(notes), examples


def parse_page(stem: str, text: str, ids: set[str], folder: str = "library") -> list[ApiEntry]:
    sections = split_sections(text)
    if not sections:
        return []
    add_anchors(sections, ids)
    title = sections[0].path[0]
    module = _page_module(stem, title)
    url = f"{BASE_URL}/{folder}/{stem}.html"
    entries: list[ApiEntry] = []
    module_entry = None
    if module and module != "builtins":
        module_entry = ApiEntry("python", "cpython", module, module, module, module, "module", url)
        entries.append(module_entry)
    module = module or stem.split("-")[0]

    for sec in sections:
        signature = sec.path[-1]
        is_api = _is_signature(signature) or (len(sec.path) > 1 and _is_member_signature("   " + signature))
        if not is_api:
            description, notes, examples = _entry_parts(sec.body, title)
            if module_entry is None:
                continue
            if len(sec.path) == 1:
                module_entry.description, module_entry.notes = description, notes
            for ex in examples:
                if ex.title == f"{title} example":
                    ex.title = sec.path[-1]
            module_entry.examples += examples
            continue

        short = _api_name(signature)
        qualified = sec.anchor if sec.anchor and sec.anchor.endswith(short) else short
        if module != "builtins" and not qualified.startswith(module + ".") and qualified != module:
            qualified = f"{module}.{qualified}"
        name = qualified.split(".")[-1]
        owner = qualified[len(module) + 1:] if qualified.startswith(module + ".") else qualified
        obj = owner.rsplit(".", 1)[0] if "." in owner else module
        keyword = API_KEYWORDS_RE.match(signature).group(0).strip().lstrip("@").split()
        if "class" in keyword:
            kind = "class"
        elif "exception" in keyword:
            kind = "exception"
        elif "(" not in signature:
            kind = "attribute"
        else:
            kind = "method" if obj != module else "function"
        description, notes, examples = _entry_parts(sec.body, qualified)
        entries.append(ApiEntry(
            language="python", runtime="cpython", module=module, object=obj, name=name, full_name=qualified,
            kind=kind, url=f"{url}#{sec.anchor}" if sec.anchor else url, signature="\n".join([signature] + sec.overloads),
            description=description, parameters=parse_parameters(signature), notes=notes, examples=examples,
        ))
    return entries
