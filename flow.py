"""Answers a question about JavaScript, Node.js or Python from the vector database.

Usage:
    python flow.py "What is map used for?"
    python flow.py "Give me an example of Array.map in JavaScript"
    python flow.py --no-cache "What is map used for?"   # skip the answer cache

A CrewAI Flow orchestrates the steps; each one has a single job:

    understand        question -> language, function names, intent, English search text
       ├── function_search   exact names + semantic search over the function records
       └── example_search    examples of those names + semantic search over example records
    build_context     picks the functions of each language and their examples
    write_answer      the "Documentation writer" agent (Ollama) explains them using only that
                      context, one task per language; the examples are shown verbatim after it

Function Search and Example Search run in parallel. When the question names no language
and several languages have the function ("What is map used for?"), the answer has one
section per language. Answers are always in English. Only two steps call the LLM:
translating a question asked in another language, and writing the answer.
"""

import re
import sys
import time
from typing import Any, Callable

import requests

import config  # noqa: F401  (disables telemetry before crewai is imported)
from crewai import LLM, Agent, Crew, Task
from crewai.events import crewai_event_bus
from crewai.events.types.llm_events import LLMStreamChunkEvent
from crewai.flow.flow import Flow, and_, listen, start
from pydantic import BaseModel, Field

import answer_cache
from config import ANSWER_CACHE_TTL, LLM_MAX_TOKENS, LLM_MODEL, LLM_TIMEOUT, MODEL_KEEP_ALIVE, OLLAMA_URL
from entries import short_title
from languages import LANGUAGES
from query import Name, Query, analyze, clean_translation, is_english, is_readable
from store import embed_query, examples_for, find_by_name, get_collection, vector_search

MAX_FUNCTIONS = 3         # per language
MAX_LANGUAGES = 4
EXACT_NAME_BONUS = 0.10   # same case as typed: "map" is Array.prototype.map, "Map" is the Map class
STRONG_NAME_BONUS = 0.10  # names written as code (`map`, Array.map) are what the user means
# Tie-breaker between near-equal matches: an entry with an official example makes a better
# answer, because its example is shown as documented instead of written by the model.
HAS_EXAMPLE_BONUS = 0.03
# The best semantic match must be at least this similar to the question. In our tests,
# on-topic questions scored 0.69 or more and off-topic ones ("what is the weather today")
# 0.58 or less.
MIN_RELEVANCE = 0.62
# When the question names no language, every language whose best match is this close to the
# overall best one gets its own section. A shared function name ("map") makes the languages
# comparable; a semantic match alone is less certain, so it must be almost as good.
LANGUAGE_MARGIN = 0.08
SEMANTIC_LANGUAGE_MARGIN = 0.03
TRANSLATE_PROMPT = (
    "Translate this question about programming into English. Translate only: keep code and "
    "function names exactly as written, add nothing. Reply with the translation only.\n\n"
    "Question: {question}"
)
NOTHING_FOUND = "Nothing relevant was found in the documentation."
# Languages qwen2.5:3b translates reliably, shown when it could not read a question.
QUESTION_LANGUAGES = "English, Português, Español, Français, Deutsch, Italiano, Русский, 中文, 日本語, 한국어"
NOT_UNDERSTOOD = (
    "Sorry, I could not understand the question. Please ask it in one of these languages: "
    f"{QUESTION_LANGUAGES}. Write function names as they appear in code (`map`, `await`, `fs.readFile`)."
)
GENERATED_NOTE = "Example written by the model: the official documentation has no example for this function."
INTENT_RULES = {
    "explain": "Explain what it is for and how it is used, in two or three sentences.",
    "example": "Explain in one sentence what it does; the examples are the focus of the answer.",
    "parameters": "List each parameter with a short explanation, then what it returns.",
    "compare": "Say in one sentence what each one does, then give the difference in two or three bullet points.",
}
# Answer length is what costs time: qwen2.5:3b writes ~50 tokens per second on an M1 Pro.
MAX_WORDS = 100


def llm(stream: bool = False) -> LLM:
    return LLM(model=f"ollama/{LLM_MODEL}", base_url=OLLAMA_URL, temperature=0.2,
               timeout=LLM_TIMEOUT, max_tokens=LLM_MAX_TOKENS, stream=stream)


def keep_model_loaded() -> None:
    """Loads the LLM, or keeps it loaded, for MODEL_KEEP_ALIVE. CrewAI talks to Ollama's
    OpenAI-compatible API, which ignores keep_alive, so each answer resets the model to
    Ollama's 5-minute default: this request, on the native API, sets it again. An empty
    prompt loads the model without generating anything."""
    try:
        requests.post(f"{OLLAMA_URL}/api/generate", json={"model": LLM_MODEL, "keep_alive": MODEL_KEEP_ALIVE}, timeout=120)
    except requests.RequestException:
        pass  # only a speed-up


class Section(BaseModel):
    """The part of the answer about one language."""
    language: str
    score: float = 0.0                                   # its best match, to rank and filter languages
    functions: list[dict] = Field(default_factory=list)  # function records chosen for it
    examples: list[dict] = Field(default_factory=list)   # their documentation examples
    context: str = ""                                    # what the writer reads
    explanation: str = ""                                # what the writer wrote

    @property
    def generated_example(self) -> bool:
        """With no documentation example, the writer is asked to write one."""
        return not self.examples


class DocsState(BaseModel):
    """Everything the flow produces, step by step. The UI shows it as the answer's trace, and
    the answer cache stores it."""
    question: str = ""
    query: dict = Field(default_factory=dict)               # query.Query, as a dict
    query_vector: list[float] = Field(default_factory=list)  # embedding of the English question
    name_hits: dict[str, list[dict]] = Field(default_factory=dict)          # name -> functions, every language
    vector_functions: dict[str, list[dict]] = Field(default_factory=dict)   # language -> functions
    name_examples: list[dict] = Field(default_factory=list)    # examples of the named functions
    vector_examples: list[dict] = Field(default_factory=list)  # examples closest to the question
    sections: list[Section] = Field(default_factory=list)      # one per language in the answer
    answer: str = ""
    timings: dict[str, float] = Field(default_factory=dict)
    tokens: dict[str, int] = Field(default_factory=lambda: {"prompt": 0, "completion": 0, "requests": 0})
    understood: bool = True  # False when the question could not be translated into English
    cached: bool = False  # answered from the answer cache, without the LLM
    original: dict[str, float] = Field(default_factory=dict)  # seconds and tokens of the first answer

    def count_tokens(self, usage: Any) -> None:
        """Adds an LLM usage report (CrewAI's UsageMetrics or a summary dict)."""
        get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
        self.tokens["prompt"] += get("prompt_tokens", 0) or 0
        self.tokens["completion"] += get("completion_tokens", 0) or 0
        self.tokens["requests"] += get("successful_requests", 0) or 0


def _timed(step):
    """Records a step's duration in state.timings (and prints it when logging)."""
    def wrapper(self, *_):  # the Flow passes the previous step's result; state is used instead
        start = time.monotonic()
        result = step(self)
        self.state.timings[step.__name__] = round(time.monotonic() - start, 2)
        if self.log:
            print(f"[{step.__name__}] {self.state.timings[step.__name__]}s", file=sys.stderr)
        return result
    wrapper.__name__ = step.__name__
    return wrapper


class DocsFlow(Flow[DocsState]):
    """on_sections(sections) is called when the functions and examples of each language are
    chosen, and on_text(section_index, text) each time the writer adds text to a section,
    so a UI can show the answer while it is being written. Both are called from worker threads."""

    suppress_flow_events = True  # no CrewAI console panels: the CLI prints one line per step

    def __init__(self, log: bool = True, on_sections: Callable[[list["Section"]], None] | None = None,
                 on_text: Callable[[int, str], None] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.log, self.on_sections, self.on_text = log, on_sections, on_text

    @property
    def q(self) -> Query:
        data = self.state.query
        return Query(**{**data, "names": [Name(**n) for n in data.get("names", [])]})

    def languages(self) -> list[str]:
        """The language the question asks about, or every language."""
        return [self.q.language] if self.q.language else list(LANGUAGES)

    # ------------------------------------------------------------------ 1. understand

    @start()
    @_timed
    def understand(self):
        question = self.state.question
        english = None
        if not is_english(question):
            # Answers are in English, and nomic-embed-text only understands English.
            if is_readable(question):
                translator = llm()
                english = clean_translation(translator.call(TRANSLATE_PROMPT.format(question=question)))
                self.state.count_tokens(translator.get_token_usage_summary())
            if english is None:
                # Searching with a failed translation answers some other question.
                self.state.understood = False
                self.state.query = Query(question=question, search_text=question).__dict__
                return
        query = analyze(question, english)
        self.state.query = {**query.__dict__, "names": [n.__dict__ for n in query.names]}
        self.state.query_vector = embed_query(query.search_text)

    # ------------------------------------------------------------------ 2a. function search

    @listen(understand)
    @_timed
    def function_search(self):
        if not self.state.understood:
            return
        q, vector = self.q, self.state.query_vector
        for name in q.names:
            ranked = rank_name_hits(name, find_by_name(name.text, vector, q.language))
            if ranked:
                self.state.name_hits[name.text] = ranked
        for lang in self.languages():
            # "in node" searches the Node.js runtime first, then all of JavaScript if it has nothing.
            runtime = q.runtime if lang == q.language else None
            self.state.vector_functions[lang] = vector_search(vector, "function", n=6, language=lang, runtime=runtime) \
                or vector_search(vector, "function", n=6, language=lang)

    # ------------------------------------------------------------------ 2b. example search

    @listen(understand)
    @_timed
    def example_search(self):
        if not self.state.understood:
            return
        q, vector = self.q, self.state.query_vector
        ids = [h["id"] for name in q.names for h in find_by_name(name.text, vector, q.language)[:30]]
        self.state.name_examples = examples_for(ids)
        for lang in self.languages():
            runtime = q.runtime if lang == q.language else None
            self.state.vector_examples += vector_search(vector, "example", n=4, language=lang, runtime=runtime) \
                or vector_search(vector, "example", n=4, language=lang)

    # ------------------------------------------------------------------ 3. context

    @listen(and_(function_search, example_search))
    @_timed
    def build_context(self):
        q, s = self.q, self.state
        s.sections = choose_sections(q, s.name_hits, s.vector_functions, self.languages())
        per_function = 2 if q.intent == "example" else 1
        for section in s.sections:
            for f in section.functions:
                # A named function shows its examples in documentation order (the first one
                # is the canonical one); a how-to question shows the closest example first.
                by_name = sorted((e for e in s.name_examples if e["function_id"] == f["id"]), key=lambda e: e["example_number"])
                by_meaning = [e for e in s.vector_examples if e["function_id"] == f["id"]]
                linked = by_name + by_meaning if s.name_hits else by_meaning + by_name
                if not linked:
                    linked = examples_for([f["id"]])
                section.examples += list({e["id"]: e for e in linked}.values())[:per_function]
            if section.functions and not section.examples and not s.name_hits:
                # A how-to question may be answered by an example of a sibling entry (another
                # method of the same object), never by an unrelated one.
                first = section.functions[0]
                section.examples = [e for e in s.vector_examples
                                    if e["object"] == first["object"] and e["module"] == first["module"]][:1]
            section.context = format_context(section.functions, section.examples)
        if s.sections:
            keep_model_loaded()  # load it now if Ollama unloaded it, before the writer needs it
        if self.on_sections:
            self.on_sections([section.model_copy(deep=True) for section in s.sections])

    # ------------------------------------------------------------------ 4. answer

    @listen(build_context)
    @_timed
    def write_answer(self):
        q, s = self.q, self.state
        if not s.sections:
            s.answer = NOTHING_FOUND if s.understood else NOT_UNDERSTOOD
            return s.answer
        writer = Agent(
            role="Documentation writer",
            goal="Explain functions to developers clearly and briefly, using only the official documentation it is given.",
            backstory="You turn official reference documentation into short, precise explanations. "
                      "You never add facts that are not in the documentation.",
            llm=llm(stream=self.on_text is not None),
            max_iter=1,
            verbose=False,
        )
        # One task per language, each with only that language's documentation. The inputs
        # are named per task (context_1, context_2...) because code in the documentation can
        # contain {braces} that must not be read as placeholders.
        inputs = {"question": q.search_text, "intent_rule": INTENT_RULES[q.intent]}
        tasks = []
        for i, section in enumerate(s.sections, 1):
            language = LANGUAGES[section.language]
            inputs[f"language_{i}"] = language.label
            inputs[f"context_{i}"] = section.context
            inputs[f"code_rule_{i}"] = (
                "Do not write any code: the documentation examples are shown to the reader after your text."
                if section.examples else
                f"The documentation has no example for this. End with ONE short, simple, runnable ```{language.fence} "
                "example that uses it and prints its result."
            )
            tasks.append(Task(
                description=(
                    "Question: {question}\n\n"
                    f"Answer it for {{language_{i}}} only.\n\n"
                    f"Documentation retrieved from the vector database (your only source):\n\n{{context_{i}}}\n\n"
                    "Rules:\n"
                    "- Write in English.\n"
                    "- Start with one sentence saying what it is for, e.g. \"`map()` creates...\".\n"
                    "- {intent_rule}\n"
                    "- Use only the documentation above. If it does not answer the question, say so.\n"
                    f"- {{code_rule_{i}}}\n"
                    f"- No title, no links, no reference list. At most {MAX_WORDS} words."
                ),
                expected_output="A short explanation in markdown.",
                agent=writer,
                context=[],  # tasks are independent: each one sees only its own documentation
                # CrewAI starts every section at once. Ollama serves one request at a time by
                # default (OLLAMA_NUM_PARALLEL=1), so it still writes them one after another.
                async_execution=i < len(s.sections),
            ))
        crew = Crew(agents=[writer], tasks=tasks, verbose=False, tracing=False)
        section_of = {str(task.id): i for i, task in enumerate(tasks)}
        written = [""] * len(tasks)
        with crewai_event_bus.scoped_handlers():  # listen only while this answer is written
            @crewai_event_bus.on(LLMStreamChunkEvent)
            def stream(_source, event):
                i = section_of.get(str(event.task_id))
                if i is not None and self.on_text:
                    written[i] += event.chunk
                    self.on_text(i, written[i])

            result = crew.kickoff(inputs=inputs)
        s.count_tokens(result.token_usage)
        for section, task in zip(s.sections, tasks):
            section.explanation = task.output.raw.strip()
        s.answer = assemble(s.sections)
        keep_model_loaded()  # CrewAI's requests set the model's expiry back to 5 minutes
        return s.answer


# ------------------------------------------------------------------ helpers

def rank_name_hits(name: Name, hits: list[dict]) -> list[dict]:
    """The functions found for a name, best first. Their similarity to the question gets a
    bonus for the same case as typed, for a name written as code, and for having an official
    example. A plain word ("today" in "what is the weather today") only names a function
    when some function of that name is relevant to the question: otherwise, no hits."""
    if not name.strong and max((h["score"] for h in hits), default=0) < MIN_RELEVANCE:
        return []
    typed = name.text.split(".")[-1]
    for h in hits:
        h["score"] = round(h["score"] + (EXACT_NAME_BONUS if h["function"] == typed else 0)
                           + (STRONG_NAME_BONUS if name.strong else 0)
                           + (HAS_EXAMPLE_BONUS if h.get("examples") else 0), 4)
    return sorted(hits, key=lambda h: -h["score"])[:12]


def choose_sections(q: Query, name_hits: dict[str, list[dict]], vector_hits: dict[str, list[dict]],
                    languages: list[str]) -> list[Section]:
    """For each language: one function per name the question mentions (the best-scored one),
    or its best semantic match when the question names none. A language is left out when its
    best match is more than LANGUAGE_MARGIN (SEMANTIC_LANGUAGE_MARGIN without a name) below
    the best language's."""
    sections = []
    for lang in languages:
        chosen: list[dict] = []
        if name_hits:
            for hits in name_hits.values():
                same = [h for h in hits if h["language"] == lang]
                if same and same[0]["id"] not in {c["id"] for c in chosen}:
                    chosen.append(same[0])
        else:
            chosen = [h for h in vector_hits.get(lang, [])[:1] if h["score"] >= MIN_RELEVANCE]
        if chosen:
            sections.append(Section(language=lang, score=max(c["score"] for c in chosen), functions=chosen[:MAX_FUNCTIONS]))
    if not sections:
        return []
    best = max(s.score for s in sections)
    margin = LANGUAGE_MARGIN if name_hits else SEMANTIC_LANGUAGE_MARGIN
    sections = [s for s in sections if s.score >= best - margin]
    return sorted(sections, key=lambda s: -s.score)[:MAX_LANGUAGES]


def format_context(functions: list[dict], examples: list[dict]) -> str:
    """The functions' records, and only the title and output of their examples: the examples
    are shown to the reader verbatim, so the model does not need to read their code (every
    token of context costs time)."""
    parts = [f"## Function {i}\n{f['text']}" for i, f in enumerate(functions, 1)]
    for i, e in enumerate(examples, 1):
        example = f"## Documentation example {i} ({e['full_name']}): {short_title(e['title'])}"
        if e.get("output"):
            example += f"\nOutput: {e['output'][:300]}"
        parts.append(example)
    return "\n\n".join(parts)


def assemble_section(section: Section) -> str:
    """The writer's explanation, then the documentation examples exactly as the documentation
    shows them, then links to the sources."""
    explanation = section.explanation
    if section.examples:
        explanation = re.sub(r"```.*?```", "", explanation, flags=re.DOTALL).strip()  # examples come from the docs
    parts = [explanation]
    if section.generated_example:
        parts.append(f"_{GENERATED_NOTE}_")
    for e in section.examples:
        parts.append(f"**Example** ({e['full_name']}): {short_title(e['title'])}")
        parts.append(f"```{e['lang']}\n{e['code']}\n```")
        if e["output"]:
            parts.append(f"**Output:**\n\n```text\n{e['output']}\n```")
    links = {f["url"]: f["full_name"] for f in section.functions}
    links.update({e["url"]: e["full_name"] for e in section.examples if e["url"] not in links})
    parts.append("**Sources:** " + " · ".join(f"[{name}]({url})" for url, name in links.items()))
    return "\n\n".join(parts)


def assemble(sections: list[Section]) -> str:
    """One section per language; a heading only when there is more than one."""
    if len(sections) == 1:
        return assemble_section(sections[0]) + "\n"
    return "\n\n".join(f"### {LANGUAGES[s.language].label}\n\n{assemble_section(s)}" for s in sections) + "\n"


def ask(question: str, log: bool = True, on_sections: Callable[[list[Section]], None] | None = None,
        on_text: Callable[[int, str], None] | None = None, use_cache: bool = True) -> DocsState:
    """Answers from the answer cache when the same question was answered in the last
    ANSWER_CACHE_TTL seconds with the same model and index, otherwise runs the flow."""
    start = time.monotonic()
    use_cache = use_cache and ANSWER_CACHE_TTL > 0
    index_version = str(get_collection().count())  # re-indexing changes the key
    if use_cache and (hit := answer_cache.get(question, index_version)):
        state = DocsState.model_validate(hit)
        state.original = {"seconds": round(sum(state.timings.values()), 2),
                          "tokens": state.tokens["prompt"] + state.tokens["completion"]}
        state.cached = True
        state.timings = {"answer_cache": round(time.monotonic() - start, 3)}
        state.tokens = {"prompt": 0, "completion": 0, "requests": 0}
        return state
    flow = DocsFlow(log=log, on_sections=on_sections, on_text=on_text)
    flow.kickoff(inputs={"question": question})
    if use_cache and flow.state.sections:  # failures raise, and are never cached
        answer_cache.put(question, index_version, flow.state.model_dump(exclude={"query_vector"}))
    return flow.state


if __name__ == "__main__":
    from preflight import check_services

    check_services()
    args = [a for a in sys.argv[1:] if a != "--no-cache"]
    question = " ".join(args) or "What is map used for?"
    start = time.monotonic()
    state = ask(question, use_cache="--no-cache" not in sys.argv)
    print("\n" + state.answer)
    summary = " | ".join(
        f"{s.language}: {', '.join(f['id'] for f in s.functions)} ({len(s.examples)} examples)" for s in state.sections
    )
    tokens = state.tokens
    cost = (f"from the answer cache (first answer: {state.original['seconds']}s, {state.original['tokens']:.0f} tokens)"
            if state.cached else
            f"{tokens['prompt']} prompt + {tokens['completion']} completion tokens in {tokens['requests']} LLM calls")
    print(f"[{time.monotonic() - start:.1f}s | {cost} | {summary or 'nothing found'}]", file=sys.stderr)
