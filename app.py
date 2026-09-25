"""Web UI: ask a question, and see every step that built the answer.

Usage:
    streamlit run app.py
"""

import queue
import threading
import time

import config  # noqa: F401  (disables telemetry before crewai is imported)
import streamlit as st

from config import EMBED_MODEL, LLM_MODEL
from languages import LANGUAGES, RUNTIMES, describe
from preflight import ollama_problems

st.set_page_config(page_title="Local Docs RAG", page_icon="📚", layout="wide")

EXAMPLES = [
    "What is map used for?",
    "How do I use map in Python?",
    "Give me an example of Array.map in JavaScript",
    "What is the difference between map and filter?",
    "What parameters does map take?",
    "How do I read a file line by line in Node.js?",
]


@st.cache_data(ttl=30)
def service_status() -> dict:
    """Ollama, models and record counts. Cached for 30 seconds: Streamlit reruns this script
    on every click, and the sidebar does not need to query Ollama and Chroma each time."""
    problems = ollama_problems()
    if problems:
        return {"problems": problems, "stats": None}
    from store import stats

    return {"problems": [], "stats": stats()}


@st.cache_resource
def warm_up() -> None:
    """Loads the LLM once when the UI starts, so the first question does not wait for it."""
    from flow import keep_model_loaded

    keep_model_loaded()


with st.sidebar:
    st.header("Local services")
    status = service_status()
    for problem in status["problems"]:
        st.error(problem)
    if not status["problems"]:
        st.success(f"Ollama: {LLM_MODEL} + {EMBED_MODEL}")
    stats = status["stats"]
    if stats and stats["total"]:
        st.success(f"Vector database: {stats['total']:,} records")
        for runtime in RUNTIMES.values():
            f, e = stats["by_source"].get(f"{runtime.key}/function", 0), stats["by_source"].get(f"{runtime.key}/example", 0)
            st.caption(f"{describe(runtime.language, runtime.key)}: {f:,} functions · {e:,} examples")
    elif not status["problems"]:
        st.error("The vector database is empty. Run: python ingest.py")
    st.caption("Everything runs on this machine.")
    usage_box = st.empty()  # filled after the question runs, so it shows the current one


def usage_line(state) -> str:
    """'5.3s · 1,262 tokens (1,032 in, 230 out) · 2 LLM calls', or where a cached answer came from."""
    t = state.tokens
    if state.cached:
        return (f"{sum(state.timings.values()):.2f}s · from the answer cache, 0 tokens "
                f"(first answer: {state.original['seconds']:.1f}s, {state.original['tokens']:,.0f} tokens)")
    return (f"{sum(state.timings.values()):.1f}s · {t['prompt'] + t['completion']:,} tokens "
            f"({t['prompt']:,} in, {t['completion']:,} out) · {t['requests']} LLM call{'s' * (t['requests'] != 1)}")


def show_usage() -> None:
    """Last question and session totals, in the sidebar. Local models: tokens cost time, not money."""
    last, total = st.session_state.get("last"), st.session_state.get("usage")
    if not last:
        return
    with usage_box.container():
        st.header("Usage")
        t = last.tokens
        seconds = sum(last.timings.values())
        c1, c2 = st.columns(2)
        c1.metric("Last answer", f"{seconds:.2f}s" if last.cached else f"{seconds:.1f}s")
        c2.metric("Tokens", f"{t['prompt'] + t['completion']:,}")
        if last.cached:
            st.caption(f"From the answer cache. The first answer took {last.original['seconds']:.1f}s "
                       f"and {last.original['tokens']:,.0f} tokens.")
        else:
            st.caption(f"{t['prompt']:,} prompt + {t['completion']:,} completion tokens in {t['requests']} LLM call(s). "
                       f"Answer writing: {last.timings.get('write_answer', 0):.1f}s.")
        st.caption(f"This session: {total['questions']} question(s), {total['cached']} from the cache, "
                   f"{total['tokens']:,} tokens, {total['seconds']:.0f}s. Local models, so no API cost.")


def ask_streaming(question: str, progress, area):
    """Runs the flow in a worker thread and shows each language's section while the model
    writes it. CrewAI calls back from its own threads and Streamlit only draws from this
    one, so the callbacks put events on a queue that this loop reads."""
    from flow import assemble, ask

    events: queue.Queue = queue.Queue()
    outcome = {}

    def work():
        try:
            outcome["state"] = ask(question, log=False, on_sections=lambda s: events.put(("sections", s)),
                                   on_text=lambda i, text: events.put(("text", i, text)))
        except Exception as exc:  # re-raised below, in the script thread
            outcome["error"] = exc
        finally:
            events.put(("done",))

    threading.Thread(target=work, daemon=True).start()
    sections, drawn = [], 0.0
    while (event := events.get())[0] != "done":
        if event[0] == "sections":
            sections = event[1]
            for section in sections:
                section.explanation = "_Writing..._"
            languages = " and ".join(LANGUAGES[s.language].label for s in sections)
            progress.update(label=f"Writing the answer ({languages})..." if sections else "Nothing found")
        else:
            _, i, text = event
            sections[i].explanation = text + " ▌"
        # Redraw at most every 50 ms, and always once the queue is drained.
        if sections and (event[0] == "sections" or events.empty() or time.monotonic() - drawn > 0.05):
            area.markdown(assemble(sections))
            drawn = time.monotonic()
    area.empty()  # the finished answer is drawn below, next to how it was built
    if "error" in outcome:
        raise outcome["error"]
    return outcome["state"]


ready = not status["problems"] and bool(stats and stats["total"])
if ready:
    warm_up()

st.title("Local Docs RAG")
st.caption("Official documentation → vector database → CrewAI → Ollama")
ask_tab, db_tab = st.tabs(["Ask", "Vector database"])

with ask_tab:
    chosen = st.pills("Examples", EXAMPLES, label_visibility="collapsed")
    # Label, question and button on one line; a form so Enter also asks.
    with st.form("ask", border=False):
        label_col, input_col, button_col = st.columns([1, 8, 1.4], vertical_alignment="center")
        label_col.markdown("**Question:**")
        question = input_col.text_input("Question", value=chosen or "", placeholder="What is map used for?",
                                        label_visibility="collapsed")
        submitted = button_col.form_submit_button("Ask", type="primary", disabled=not ready, width="stretch")
    if submitted and question.strip():
        progress = st.status("Searching the documentation...")
        try:
            state = ask_streaming(question, progress, st.empty())
        except Exception as exc:  # Ollama down, LLM timeout...
            progress.update(label="Failed", state="error")
            st.error(f"The question could not be answered: {exc}")
            state = None
        else:
            progress.update(label=f"Done: {usage_line(state)}", state="complete")
        if state:
            st.session_state["last"] = state
            total = st.session_state.setdefault("usage", {"questions": 0, "cached": 0, "tokens": 0, "seconds": 0.0})
            total["questions"] += 1
            total["cached"] += state.cached
            total["tokens"] += state.tokens["prompt"] + state.tokens["completion"]
            total["seconds"] += sum(state.timings.values())

    if "last" in st.session_state:
        s = st.session_state["last"]
        answer_col, trace_col = st.columns([3, 2])
        with answer_col:
            st.caption(usage_line(s))
            st.markdown(s.answer)
        with trace_col:
            st.subheader("How the answer was built")
            st.caption(" → ".join(f"{step} {t}s" for step, t in s.timings.items()))
            q = s.query
            with st.expander("1. Understand the question", expanded=True):
                names = ", ".join(f"`{n['text']}`" for n in q["names"]) or "none"
                if not s.understood:
                    st.markdown("The question could not be translated into English, so it was not searched.")
                else:
                    st.markdown(
                        f"- **Language:** {q['language'] or 'not stated'}" + (f" ({q['runtime']})" if q["runtime"] else "") + "\n"
                        f"- **Function names:** {names}\n"
                        f"- **Intent:** {q['intent']}\n"
                        f"- **Embedded text:** {q['search_text']}"
                        + ("" if q["search_text"] == q["question"] else " (translated to English)")
                    )
            with st.expander("2a. Function search"):
                for name, hits in s.name_hits.items():
                    st.markdown(f"Exact name `{name}`:")
                    st.dataframe([{"id": h["id"], "full name": h["full_name"], "score": h["score"]} for h in hits],
                                 hide_index=True)
                for lang, hits in s.vector_functions.items():
                    st.markdown(f"Semantic search, {LANGUAGES[lang].label}:")
                    st.dataframe([{"id": h["id"], "full name": h["full_name"], "score": h["score"]} for h in hits],
                                 hide_index=True)
            with st.expander("2b. Example search"):
                rows = [{"id": e["id"], "title": e["title"], "via": "name"} for e in s.name_examples[:15]]
                rows += [{"id": e["id"], "title": e["title"], "via": f"semantic {e['score']}"} for e in s.vector_examples]
                st.dataframe(rows, hide_index=True)
            with st.expander(f"3. Context sent to Ollama ({len(s.sections)} language(s))"):
                if not s.sections:
                    st.markdown("Nothing relevant was found.")
                for section in s.sections:
                    st.markdown(f"**{LANGUAGES[section.language].label}** (score {section.score}): "
                                + ", ".join(f"`{f['id']}`" for f in section.functions)
                                + ("  \nExamples: " + ", ".join(f"`{e['id']}`" for e in section.examples)
                                   if section.examples else "  \nNo documentation example: the model writes one."))
                    st.code(section.context, language="markdown")

with db_tab:
    st.caption("Queries the vector database directly, without the LLM.")
    text = st.text_input("Search", placeholder="create a new array from the results of a function")
    c1, c2, c3 = st.columns(3)
    record_type = c1.selectbox("Record type", ["function", "example"])
    language = c2.selectbox("Language", ["any", *LANGUAGES])
    mode = c3.selectbox("Match", ["semantic", "exact name"],
                        help="Exact name looks up function records by name (map, Array.map, fs.readFile), "
                             "whatever the record type.")
    if text and ready:
        from store import embed_query, find_by_name, vector_search

        lang = None if language == "any" else language
        if mode == "semantic":
            hits = vector_search(embed_query(text), record_type, n=8, language=lang)
        else:
            hits = find_by_name(text.strip(), embed_query(text), lang)
        if not hits:
            st.info("No records found.")
        for h in hits:
            with st.expander(f"{h['id']} · {h['full_name']} · score {h['score']}"):
                st.json({k: v for k, v in h.items() if k not in ("text", "code")}, expanded=False)
                st.text(h["text"])

# Last, so the sidebar shows the question that has just been answered.
show_usage()
