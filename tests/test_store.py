"""Metadata lookups on a real, in-memory Chroma collection with hand-made 3-dimensional
vectors: no Ollama needed."""

import chromadb
import pytest

import store
from entries import ApiEntry, CodeExample, assign_ids, to_chunks

# Unit vectors: the "question" below points at arrays.
ARRAYS, PYTHON, FILES = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]


def entry(language, runtime, module, obj, name, full_name, vector, examples=0):
    e = ApiEntry(language, runtime, module, obj, name, full_name, "method", f"https://x/{full_name}",
                 examples=[CodeExample(f"example {i}", f"code {i}", "js") for i in range(1, examples + 1)])
    e.vector = vector
    return e


@pytest.fixture
def records(monkeypatch):
    entries = [
        entry("javascript", "ecmascript", "Array", "Array", "map", "Array.prototype.map", ARRAYS, examples=2),
        entry("javascript", "ecmascript", "TypedArray", "TypedArray", "map", "TypedArray.prototype.map", [0.9, 0.1, 0.0]),
        entry("javascript", "ecmascript", "Map", "Map", "Map", "Map", [0.8, 0.0, 0.2]),
        entry("python", "cpython", "builtins", "builtins", "map", "map", PYTHON),
        entry("javascript", "nodejs", "fs", "fs", "readFile", "fs.readFile", FILES, examples=1),
        entry("javascript", "nodejs", "path", "path", "join", "path.join", [0.0, 0.2, 0.8]),
    ]
    assign_ids(entries)
    collection = chromadb.EphemeralClient().get_or_create_collection("records_test", metadata={"hnsw:space": "cosine"})
    for e in entries:
        chunks = to_chunks(e)
        collection.add(ids=[c["id"] for c in chunks], documents=[c["text"] for c in chunks],
                       metadatas=[c["metadata"] for c in chunks], embeddings=[e.vector] * len(chunks))
    monkeypatch.setattr(store, "get_collection", lambda: collection)
    yield collection
    chromadb.EphemeralClient().delete_collection("records_test")


def full_names(hits):
    return sorted(h["full_name"] for h in hits)


def test_a_name_finds_every_function_of_that_name(records):
    assert full_names(store.find_by_name("map")) == ["Array.prototype.map", "Map", "TypedArray.prototype.map", "map"]
    assert full_names(store.find_by_name("map", language="python")) == ["map"]
    assert full_names(store.find_by_name("map()")) == full_names(store.find_by_name("map"))


def test_a_qualified_name_must_match_its_object_or_module(records):
    assert full_names(store.find_by_name("Array.map")) == ["Array.prototype.map"]
    assert full_names(store.find_by_name("Array.prototype.map")) == ["Array.prototype.map"]
    assert full_names(store.find_by_name("fs.readFile")) == ["fs.readFile"]
    assert store.find_by_name("path.readFile") == []


def test_names_are_scored_against_the_question(records):
    hits = {h["full_name"]: h["score"] for h in store.find_by_name("map", query_vector=ARRAYS)}
    assert hits["Array.prototype.map"] == pytest.approx(1.0)
    assert hits["map"] == pytest.approx(0.0)


def test_semantic_search_filters_by_type_and_language(records):
    functions = store.vector_search(ARRAYS, "function", n=2)
    assert [h["full_name"] for h in functions] == ["Array.prototype.map", "TypedArray.prototype.map"]
    assert functions[0]["score"] == pytest.approx(1.0)
    assert [h["full_name"] for h in store.vector_search(ARRAYS, "function", n=1, language="python")] == ["map"]
    examples = store.vector_search(ARRAYS, "example", n=5)
    assert {h["type"] for h in examples} == {"example"}
    assert [h["full_name"] for h in store.vector_search(FILES, "function", n=5, runtime="nodejs")][:1] == ["fs.readFile"]


def test_examples_of_functions_in_order(records):
    examples = store.examples_for(["nodejs_fs_readfile", "javascript_array_map"])
    assert [e["id"] for e in examples] == [
        "nodejs_fs_readfile_example_01", "javascript_array_map_example_01", "javascript_array_map_example_02"]
    assert examples[0]["code"] == "code 1"
    assert store.examples_for([]) == []
