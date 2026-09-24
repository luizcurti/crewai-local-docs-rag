from query import analyze, is_english


def names(question):
    return [(n.text, n.strong) for n in analyze(question).names]


def test_example_questions():
    q = analyze("What is map used for?")
    assert (q.language, q.intent) == (None, "explain")
    assert names("What is map used for?") == [("map", False)]
    assert analyze("How do I use map in Python?").language == "python"
    q = analyze("Give me an example of Array.map in JavaScript")
    assert (q.language, q.intent) == ("javascript", "example")
    assert names(q.question) == [("Array.map", True)]
    q = analyze("What is the difference between map and filter?")
    assert q.intent == "compare" and names(q.question) == [("map", False), ("filter", False)]
    assert analyze("What parameters does map take?").intent == "parameters"


def test_runtime_and_ordinary_words():
    q = analyze("how do I read a file line by line in node")
    assert (q.language, q.runtime) == ("javascript", "nodejs")
    assert q.names == []  # ordinary words in a sentence are not function names


def test_code_like_names_always_count():
    assert names("what does `fs.readFile` do with a file") == [("fs.readFile", True)]
    assert names("difference between list.sort() and sorted") == [("list.sort", True), ("sorted", False)]
    assert names("what is Promise.all") == [("Promise.all", True)]


def test_questions_in_other_languages_are_analyzed_in_english():
    assert is_english("What is map used for?") and is_english("Array.map")
    assert not is_english("Para que serve map?") and not is_english("¿Para qué sirve map?")
    q = analyze("Me dê um exemplo de Array.map em JavaScript", english="Give me an example of Array.map in JavaScript")
    assert (q.language, q.intent, q.search_text) == ("javascript", "example", "Give me an example of Array.map in JavaScript")
    assert [n.text for n in q.names] == ["Array.map"]
