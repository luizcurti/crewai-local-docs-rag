from sources.python import _api_name, _heading_id, _is_signature, add_anchors, parse_page, split_blocks, split_sections

TEXT = '''"pathlib" --- Object-oriented filesystem paths
**********************************************

Added in version 3.4.

======================================================================

This module offers classes representing filesystem paths.


Basic use
=========

Importing the main class:

   >>> from pathlib import Path


Pure paths
==========

class pathlib.PurePath(*pathsegments)

   A generic class that represents the system's path flavour.


Methods and properties
----------------------

PurePath.with_name(name)

   Return a new path with the "name" changed.

      >>> p.with_name('setup.py')

Plain prose after the API entry belongs to the section again.

@functools.lru_cache(user_function)
@functools.lru_cache(maxsize=128, typed=False)

   Decorator to wrap a function with a memoizing callable.

class unittest.TestCase(methodName='runTest')

   Instances of the "TestCase" class represent tests.

   assertEqual(first, second, msg=None)

      Test that *first* and *second* are equal.

   classmethod setUpClass()

      A class method called before tests in a class run.

   Prose back at the class level belongs to the class.
'''


def paths():
    return [" > ".join(s.path) for s in split_sections(TEXT)]


def test_heading_levels_follow_underline_characters():
    assert paths()[:2] == [
        "pathlib --- Object-oriented filesystem paths",
        "pathlib --- Object-oriented filesystem paths > Basic use",
    ]


def test_api_entries_become_sub_sections():
    assert "pathlib --- Object-oriented filesystem paths > Pure paths > class pathlib.PurePath(*pathsegments)" in paths()
    assert (
        "pathlib --- Object-oriented filesystem paths > Pure paths > Methods and properties > PurePath.with_name(name)"
        in paths()
    )


def test_prose_after_an_api_entry_returns_to_the_section():
    sections = {" > ".join(s.path): s.body for s in split_sections(TEXT)}
    methods = sections["pathlib --- Object-oriented filesystem paths > Pure paths > Methods and properties"]
    assert "Plain prose after the API entry" in methods


def test_decorators_and_stacked_signatures():
    decorator = [s for s in split_sections(TEXT) if s.path[-1].startswith("@functools.lru_cache")]
    assert len(decorator) == 1
    assert decorator[0].path[-1] == "@functools.lru_cache(user_function)"
    assert decorator[0].overloads == ["@functools.lru_cache(maxsize=128, typed=False)"]


def test_signature_detection():
    assert _is_signature("PurePath.with_name(name)")
    assert _is_signature("classmethod Path.from_uri(uri)")
    assert _is_signature("@dataclasses.dataclass")
    assert not _is_signature("Example")
    assert not _is_signature("   indented.call()")
    assert not _is_signature("Note:")


def test_api_name_and_heading_id():
    assert _api_name("classmethod Path.from_uri(uri)") == "Path.from_uri"
    assert _api_name("@functools.lru_cache(maxsize=128)") == "functools.lru_cache"
    assert _heading_id("5.1. More on Lists") == "more-on-lists"


def test_anchors_only_use_ids_that_exist():
    sections = split_sections(TEXT)
    add_anchors(sections, {"basic-use", "pathlib.PurePath", "pathlib.PurePath.with_name"})
    anchors = {s.path[-1]: s.anchor for s in sections}
    assert anchors["pathlib --- Object-oriented filesystem paths"] is None  # page title
    assert anchors["Basic use"] == "basic-use"
    assert anchors["PurePath.with_name(name)"] == "pathlib.PurePath.with_name"
    assert anchors["Methods and properties"] is None  # not in the HTML ids


def test_class_members_become_their_own_sections():
    sections = split_sections(TEXT)
    titles = [s.path[-1] for s in sections]
    assert "TestCase.assertEqual(first, second, msg=None)" in titles
    assert "classmethod TestCase.setUpClass()" in titles
    member = next(s for s in sections if s.path[-1].startswith("TestCase.assertEqual"))
    assert member.path[-2] == "class unittest.TestCase(methodName='runTest')"
    assert member.body == "Test that *first* and *second* are equal."
    class_text = " ".join(s.body for s in sections if s.path[-1].startswith("class unittest.TestCase"))
    assert "Prose back at the class level" in class_text
    assert "Test that" not in class_text


def test_member_anchor_is_qualified_by_its_class():
    sections = split_sections(TEXT)
    add_anchors(sections, {"unittest.TestCase", "unittest.TestCase.assertEqual", "other.Thing.assertEqual"})
    member = next(s for s in sections if s.path[-1].startswith("TestCase.assertEqual"))
    assert member.anchor == "unittest.TestCase.assertEqual"


# ------------------------------------------------------------------ API entries

PAGE = '''Built-in Functions
******************

The Python interpreter has a number of functions built into it.

map(function, iterable, /, *iterables, strict=False)

   Return an iterator that applies *function* to every item of
   *iterable*, yielding the results.

   Changed in version 3.14: Added the *strict* parameter.

str.split(sep=None, maxsplit=-1)

   Return a list of the words in the string.

   For example:

      >>> '1,2,3'.split(',')
      ['1', '2', '3']

      >>> '1 2'.split()
      ['1', '2']

   Note:

      Splitting an empty string returns "[]".
'''


def entries():
    return {e.full_name: e for e in parse_page("functions", PAGE, {"map", "str.split"}, "builtins")}


def test_builtins_entries():
    e = entries()["map"]
    assert (e.module, e.object, e.name, e.kind) == ("builtins", "builtins", "map", "function")
    assert e.url.endswith("/builtins/functions.html#map")
    assert e.parameters == [("function", ""), ("iterable", ""), ("*iterables", ""), ("strict=False", "")]
    assert e.description.startswith("Return an iterator")
    assert e.notes == "Changed in version 3.14: Added the *strict* parameter."
    assert e.examples == []


def test_doctest_session_becomes_an_example():
    e = entries()["str.split"]
    assert (e.object, e.name, e.kind) == ("str", "split", "method")
    assert len(e.examples) == 1  # one session, even with a blank line inside it
    assert e.examples[0].code.startswith(">>> '1,2,3'.split(',')")
    assert "['1', '2']" in e.examples[0].code
    assert "For example" not in e.description  # the intro means nothing without its code
    assert "Splitting an empty string" in e.notes  # admonitions are notes, not code


def test_module_page_gets_a_module_entry():
    page = parse_page("pathlib", TEXT, set())
    module = page[0]
    assert (module.kind, module.name) == ("module", "pathlib")
    assert "This module offers classes" in module.description
    assert any(ex.code == ">>> from pathlib import Path" for ex in module.examples)
    method = next(e for e in page if e.name == "with_name")
    assert (method.full_name, method.object) == ("pathlib.PurePath.with_name", "PurePath")


def test_split_blocks_keeps_indented_code_with_blank_lines():
    blocks = split_blocks("Intro:\n\n   a = 1\n\n   b = 2\n\nAfter.")
    assert blocks == [("text", "Intro:"), ("code", "a = 1\n\nb = 2"), ("text", "After.")]
