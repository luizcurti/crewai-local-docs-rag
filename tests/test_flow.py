from flow import Section, assemble, choose_sections
from languages import LANGUAGES
from query import analyze

ALL = list(LANGUAGES)


def hit(id, language, full_name, score, url="https://x", **kw):
    return {"id": id, "language": language, "full_name": full_name, "score": score, "url": url, **kw}


MAP_HITS = {"map": [hit("javascript_array_map", "javascript", "Array.prototype.map", 0.82),
                    hit("python_builtins_map", "python", "map", 0.81),
                    hit("javascript_map", "javascript", "Map", 0.77)]}


def test_a_name_in_several_languages_gets_one_section_each():
    sections = choose_sections(analyze("What is map used for?"), MAP_HITS, {}, ALL)
    assert [(s.language, [f["id"] for f in s.functions]) for s in sections] == [
        ("javascript", ["javascript_array_map"]), ("python", ["python_builtins_map"])]


def test_explicit_language_gets_only_its_section():
    sections = choose_sections(analyze("How do I use map in Python?"), {"map": MAP_HITS["map"][1:2]}, {}, ["python"])
    assert [s.language for s in sections] == ["python"]


def test_a_language_far_below_the_best_is_left_out():
    hits = {"open": [hit("python_builtins_open", "python", "open", 0.85), hit("nodejs_fs_open", "javascript", "fs.open", 0.70)]}
    assert [s.language for s in choose_sections(analyze("what does open do"), hits, {}, ALL)] == ["python"]


def test_compare_keeps_every_name_in_each_language():
    hits = {"map": MAP_HITS["map"],
            "filter": [hit("python_builtins_filter", "python", "filter", 0.8),
                       hit("javascript_array_filter", "javascript", "Array.prototype.filter", 0.79)]}
    sections = choose_sections(analyze("What is the difference between map and filter?"), hits, {}, ALL)
    assert {s.language: [f["id"] for f in s.functions] for s in sections} == {
        "javascript": ["javascript_array_map", "javascript_array_filter"],
        "python": ["python_builtins_map", "python_builtins_filter"]}


def test_without_names_each_language_uses_its_best_semantic_match():
    vector = {"javascript": [hit("nodejs_readline", "javascript", "readline", 0.74)],
              "python": [hit("python_io_readline", "python", "io.IOBase.readline", 0.72)]}
    sections = choose_sections(analyze("how do I read a file line by line"), {}, vector, ALL)
    assert [s.functions[0]["id"] for s in sections] == ["nodejs_readline", "python_io_readline"]


def test_without_names_a_clearly_weaker_language_is_left_out():
    vector = {"javascript": [hit("nodejs_urlsearchparams_sort", "javascript", "urlSearchParams.sort", 0.765)],
              "python": [hit("python_list_sort", "python", "list.sort", 0.803)]}
    sections = choose_sections(analyze("how to sort a list"), {}, vector, ALL)
    assert [s.language for s in sections] == ["python"]


def test_off_topic_questions_find_nothing():
    vector = {"python": [hit("python_datetime_today", "python", "datetime.date.today", 0.58)]}
    assert choose_sections(analyze("what is the weather in London today"), {}, vector, ALL) == []


def test_answer_shows_documentation_examples_verbatim():
    section = Section(
        language="javascript",
        explanation="`map()` creates a new array.\n\n```js\nmade.up()\n```",
        functions=[hit("javascript_array_map", "javascript", "Array.prototype.map", 0.8, url="https://mdn/map")],
        examples=[hit("javascript_array_map_example_01", "javascript", "Array.prototype.map", 0.8, url="https://mdn/map",
                      title="Demo", lang="js", code="[1].map((x) => x * 2)", output="[2]")],
    )
    answer = assemble([section])
    assert not answer.startswith("###")  # a single language needs no heading
    assert "made.up" not in answer  # the model's own code is dropped when the docs have examples
    assert "**Example** (Array.prototype.map): Demo\n\n```js\n[1].map((x) => x * 2)\n```" in answer
    assert "**Output:**\n\n```text\n[2]\n```" in answer
    assert answer.rstrip().endswith("**Sources:** [Array.prototype.map](https://mdn/map)")


def test_several_languages_get_a_heading_each_and_generated_examples_are_labelled():
    js = Section(language="javascript", explanation="JS text.",
                 functions=[hit("javascript_array_map", "javascript", "Array.prototype.map", 0.8)],
                 examples=[hit("e1", "javascript", "Array.prototype.map", 0.8, title="Demo", lang="js", code="x", output="")])
    py = Section(language="python", explanation="Py text.\n\n```python\nprint(list(map(str, [1])))\n```",
                 functions=[hit("python_builtins_map", "python", "map", 0.8)])
    answer = assemble([js, py])
    assert answer.startswith("### JavaScript\n\nJS text.")
    python_part = answer.split("### Python", 1)[1]
    assert "print(list(map(str, [1])))" in python_part
    assert "Example written by the model" in python_part
    assert "Example written by the model" not in answer.split("### Python", 1)[0]


# ------------------------------------------------------------------ ranking the functions of a name

def test_same_case_as_typed_wins():
    from flow import rank_name_hits
    from query import Name

    hits = [hit("javascript_map", "javascript", "Map", 0.745, function="Map", examples=7),
            hit("javascript_array_map", "javascript", "Array.prototype.map", 0.69, function="map", examples=9)]
    assert rank_name_hits(Name("map", False), hits)[0]["id"] == "javascript_array_map"
    hits = [hit("javascript_map", "javascript", "Map", 0.745, function="Map", examples=7),
            hit("javascript_array_map", "javascript", "Array.prototype.map", 0.69, function="map", examples=9)]
    assert rank_name_hits(Name("Map", False), hits)[0]["id"] == "javascript_map"


def test_an_official_example_breaks_near_ties():
    from flow import rank_name_hits
    from query import Name

    hits = [hit("python_builtins_map", "python", "map", 0.70, function="map", examples=0),
            hit("javascript_array_map", "javascript", "Array.prototype.map", 0.69, function="map", examples=9)]
    assert rank_name_hits(Name("map", False), hits)[0]["id"] == "javascript_array_map"


def test_a_plain_word_that_names_nothing_relevant_is_dropped():
    from flow import rank_name_hits
    from query import Name

    today = [hit("python_date_today", "python", "datetime.date.today", 0.58, function="today")]
    assert rank_name_hits(Name("today", False), today) == []
    # Written as code, the same name is kept: the user clearly means the function.
    today = [hit("python_date_today", "python", "datetime.date.today", 0.58, function="today")]
    assert [h["id"] for h in rank_name_hits(Name("today()", True), today)] == ["python_date_today"]


def test_the_context_has_no_example_code():
    from flow import format_context

    function = hit("javascript_array_map", "javascript", "Array.prototype.map", 0.8, text="Array.prototype.map (method)")
    example = hit("e1", "javascript", "Array.prototype.map", 0.8, title="Demo. More text.", code="SECRET_CODE", output="[2]")
    context = format_context([function], [example])
    assert "Array.prototype.map (method)" in context
    assert "Documentation example 1 (Array.prototype.map): Demo" in context and "Output: [2]" in context
    assert "SECRET_CODE" not in context  # shown to the reader verbatim, never sent to the LLM


# ------------------------------------------------------------------ answer cache in ask()

class FakeCollection:
    def count(self):
        return 100


def fake_flow(sections):
    """A DocsFlow stand-in that 'answers' without Ollama, and counts its runs."""
    from flow import DocsState

    class Flow:
        runs = 0

        def __init__(self, **_):
            self.state = DocsState()

        def kickoff(self, inputs):
            Flow.runs += 1
            self.state.question = inputs["question"]
            self.state.sections = sections
            self.state.answer = "the answer"
            self.state.timings = {"write_answer": 4.0}
            self.state.tokens = {"prompt": 600, "completion": 100, "requests": 1}

    return Flow


def use_fakes(monkeypatch, tmp_path, sections):
    import answer_cache
    import flow

    monkeypatch.setattr(answer_cache, "ANSWER_CACHE_DIR", tmp_path)
    monkeypatch.setattr(flow, "get_collection", FakeCollection)
    fake = fake_flow(sections)
    monkeypatch.setattr(flow, "DocsFlow", fake)
    return fake


def test_a_repeated_question_comes_from_the_cache(monkeypatch, tmp_path):
    from flow import ask

    fake = use_fakes(monkeypatch, tmp_path, [Section(language="javascript")])
    first = ask("What is map used for?", log=False)
    again = ask("what is map used for", log=False)
    assert fake.runs == 1
    assert (first.cached, again.cached) == (False, True)
    assert again.answer == "the answer"
    assert again.tokens == {"prompt": 0, "completion": 0, "requests": 0}
    assert again.original == {"seconds": 4.0, "tokens": 700}
    ask("what is map used for", log=False, use_cache=False)
    assert fake.runs == 2


def test_nothing_found_is_not_cached(monkeypatch, tmp_path):
    from flow import ask

    fake = use_fakes(monkeypatch, tmp_path, [])
    ask("what is the weather today", log=False)
    ask("what is the weather today", log=False)
    assert fake.runs == 2
