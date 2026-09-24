"""Understanding the question, in code (no LLM): language, function names and intent.

    "What is map used for?"                          -> names: map
    "How do I use map in Python?"                    -> language: python
    "Give me an example of Array.map in JavaScript"  -> names: Array.map; intent: example
    "What is the difference between map and filter?" -> names: map, filter; intent: compare
    "What parameters does map take?"                 -> intent: parameters

The names are only candidates: the Function Search step keeps the ones that exist in the
vector database. Everything is English: a question in another language is translated
first (see flow.py), then analyzed.
"""

import re
from dataclasses import dataclass, field

from languages import LANGUAGES, RUNTIMES

# Words that name a language, including its runtimes' names ("node" means JavaScript).
LANGUAGE_WORDS = {
    key: set(lang.keywords).union(*(r.keywords for r in RUNTIMES.values() if r.language == key))
    for key, lang in LANGUAGES.items()
}
# Common English words that are not short words of other languages too ("a", "de", "no"):
# a question containing none of them is translated before it is analyzed.
ENGLISH_WORDS = set(
    "what how is are does the of to for with and which when why can give show example examples "
    "difference between parameters parameter use used using explain return returns this that it "
    "an get work works i my should way make there".split()
)
STOPWORDS = ENGLISH_WORDS | set(
    "whats do did who tell me about a in on or accept accepts receive receives its vs versus by from "
    "into all each every your some any could would will module modules library lib package args "
    "arguments argument params take takes".split()
)
# Real API names that are also ordinary words: only counted when written as code
# (`function`, list(), Array.from) so "what does this function do" does not match them.
GENERIC_WORDS = set(
    "function functions method methods class classes object objects value values "
    "file files string strings number numbers array arrays list lists type types new get set "
    "print output input error errors code program data time name key keys item items this".split()
)
INTENTS = {
    "compare": {"difference", "differences", "vs", "versus", "compare", "comparison"},
    "parameters": {"parameters", "parameter", "params", "arguments", "argument", "accepts", "accept",
                   "signature", "take", "takes", "receive", "receives"},
    "example": {"example", "examples", "sample", "demo"},
}

CODE_SPAN_RE = re.compile(r"`([^`]+)`")
IDENTIFIER_RE = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\(\))?")


@dataclass
class Name:
    text: str      # "map", "Array.map", "fs.readFile"
    strong: bool   # written as code: `map`, map(), Array.map


@dataclass
class Query:
    question: str                     # as asked
    language: str | None = None       # a key of languages.LANGUAGES, when the question says so
    runtime: str | None = None        # a key of languages.RUNTIMES, e.g. "nodejs" for "in node"
    names: list[Name] = field(default_factory=list)
    intent: str = "explain"           # explain, example, parameters, compare
    search_text: str = ""             # the English question, whose embedding is searched


def _words(text: str) -> list[str]:
    return re.findall(r"[\w.$]+", text.lower())


def is_english(question: str) -> bool:
    """True when the question has an English word, or is only code ("Array.map")."""
    words = re.findall(r"[^\W\d_]+", CODE_SPAN_RE.sub(" ", question).lower())
    return not words or any(w in ENGLISH_WORDS for w in words) or bool(IDENTIFIER_RE.fullmatch(question.strip()))


def detect_language(question: str) -> tuple[str | None, str | None]:
    words = set(_words(question)) | {w.rstrip(".") for w in _words(question)}
    found = [lang for lang, keys in LANGUAGE_WORDS.items() if words & keys]
    language = found[0] if len(found) == 1 else None
    runtime = next((r.key for r in RUNTIMES.values() if r.language == language and words & r.keywords), None)
    return language, runtime


def extract_names(question: str) -> list[Name]:
    """Candidate API names, in the order they appear. Code-like tokens (`map`, map(),
    Array.map) always count. Plain words only count when the question is made of names
    and question words ("What is map used for?", "difference between map and filter"):
    in "read a file line by line", read and line are ordinary words."""
    names: dict[str, Name] = {}
    language_words = set().union(*LANGUAGE_WORDS.values())
    for span in CODE_SPAN_RE.findall(question):
        for token in IDENTIFIER_RE.findall(span):
            names.setdefault(token.removesuffix("()"), Name(token.removesuffix("()"), True))
    rest = CODE_SPAN_RE.sub(" ", question)
    for token in IDENTIFIER_RE.findall(rest):
        text = token.removesuffix("()").rstrip(".")
        strong = token.endswith("()") or "." in text
        lower = text.lower()
        if not text or lower in language_words or len(text) < 2:
            continue
        if not strong and (lower in STOPWORDS or lower in GENERIC_WORDS):
            continue
        names.setdefault(text, Name(text, strong))
    plain = IDENTIFIER_RE.sub(lambda m: " " if m.group(0).endswith("()") or "." in m.group(0) else m.group(0), rest)
    content = [w for w in re.findall(r"[^\W\d]+", plain.lower()) if w not in STOPWORDS and w not in language_words]
    if any(w in GENERIC_WORDS for w in content):
        names = {k: n for k, n in names.items() if n.strong}
    return list(names.values())


def detect_intent(question: str) -> str:
    words = set(_words(question))
    for intent, keys in INTENTS.items():
        if words & keys:
            return intent
    return "explain"


def analyze(question: str, english: str | None = None) -> Query:
    """`english` is the translation of a question asked in another language. Code-like
    names are taken from both, since a translation may reformat them."""
    text = english or question
    language, runtime = detect_language(f"{question} {text}")
    names = {n.text: n for n in extract_names(text)}
    if english:
        for n in extract_names(question):
            if n.strong:
                names.setdefault(n.text, n)
    return Query(
        question=question,
        language=language,
        runtime=runtime,
        names=list(names.values()),
        intent=detect_intent(text),
        search_text=text,
    )
