"""The languages and runtimes the system knows.

A language (JavaScript, Python) can have several runtimes, each one a documentation
source: JavaScript has the language itself (MDN) and Node.js. To add a language, e.g. Java
or C#, write a source adapter in sources/ that returns ApiEntry objects with its language
and runtime keys, and register both here: questions, record IDs, answers and the UI all
read this file.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    key: str                  # metadata value: "javascript"
    label: str                # "JavaScript"
    fence: str                # code fence for examples: "js"
    keywords: frozenset[str]  # words that name it in a question: "js", "javascript"


@dataclass(frozen=True)
class Runtime:
    key: str                  # metadata value: "nodejs"
    language: str             # Language.key
    label: str                # "Node.js runtime"
    id_prefix: str            # record IDs start with it: nodejs_fs_readfile
    keywords: frozenset[str] = frozenset()  # words that name this runtime: "node"


LANGUAGES = {lang.key: lang for lang in [
    Language("javascript", "JavaScript", "js", frozenset({"javascript", "js", "ecmascript", "typescript", "ts"})),
    Language("python", "Python", "python", frozenset({"python", "python3", "py", "cpython"})),
]}

RUNTIMES = {runtime.key: runtime for runtime in [
    Runtime("ecmascript", "javascript", "language reference, MDN", "javascript"),
    Runtime("nodejs", "javascript", "Node.js runtime", "nodejs", frozenset({"node", "nodejs", "node.js"})),
    Runtime("cpython", "python", "standard library", "python"),
]}


def describe(language: str, runtime: str) -> str:
    """'JavaScript (Node.js runtime)'."""
    return f"{LANGUAGES[language].label} ({RUNTIMES[runtime].label})"
