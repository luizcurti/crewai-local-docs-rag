from sources.mdn import _names, clean, parse_page, parse_parameters

PAGE = '''---
title: Array.prototype.map()
short-title: map()
slug: Web/JavaScript/Reference/Global_Objects/Array/map
page-type: javascript-instance-method
---

The **`map()`** method of {{jsxref("Array")}} instances creates
a new array populated with the results of calling a provided function.

{{InteractiveExample("JavaScript Demo: Array.prototype.map()")}}

```js interactive-example
const array = [1, 4, 9, 16];
const mapped = array.map((x) => x * 2);

console.log(mapped);
// Expected output: Array [2, 8, 18, 32]
```

## Syntax

```js-nolint
map(callbackFn)
map(callbackFn, thisArg)
```

### Parameters

- `callbackFn`
  - : A function to execute for each element in the array.
    - `element`
      - : The current element.
- `thisArg` {{optional_inline}}
  - : A value to use as `this`. See [iterative methods](/en-US/docs/Web).

### Return value

A new array with each element being the result of the callback function.

## Description

The `map()` method is an [iterative method](/en-US/docs/x). Use {{jsxref("Array/forEach", "forEach")}} otherwise.

## Examples

### Mapping numbers to square roots

```js
const roots = [1, 4, 9].map((num) => Math.sqrt(num));
```

### A mistake

```js example-bad
[1].map(parseInt);
```

## Browser compatibility

{{Compat}}
'''


def test_function_entry():
    e = parse_page(PAGE)
    assert (e.language, e.runtime, e.module, e.object, e.name) == ("javascript", "ecmascript", "Array", "Array", "map")
    assert (e.full_name, e.kind) == ("Array.prototype.map", "method")
    assert e.url == "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/map"
    assert e.signature == "map(callbackFn)\nmap(callbackFn, thisArg)"
    assert e.description.startswith("The **`map()`** method of `Array` instances creates a new array")
    assert e.parameters == [
        ("callbackFn", "A function to execute for each element in the array."),
        ("thisArg (optional)", "A value to use as `this`. See iterative methods."),
    ]
    assert e.returns == "A new array with each element being the result of the callback function."
    assert e.notes == "The `map()` method is an iterative method. Use `forEach` otherwise."


def test_examples_keep_their_expected_output_separately():
    examples = parse_page(PAGE).examples
    assert [ex.title for ex in examples] == ["JavaScript Demo: Array.prototype.map()", "Mapping numbers to square roots"]
    demo = examples[0]
    assert "Expected output" not in demo.code
    assert demo.output == "Array [2, 8, 18, 32]"
    assert "parseInt" not in "".join(ex.code for ex in examples)  # example-bad blocks are skipped


def test_pages_that_are_not_api_entries_are_skipped():
    assert parse_page(PAGE.replace("javascript-instance-method", "javascript-error")) is None


def test_names_from_slug():
    base = "Web/JavaScript/Reference/"
    assert _names(base + "Global_Objects/parseInt", "parseInt()") == ("globalThis", "parseInt", "parseInt")
    assert _names(base + "Global_Objects/Promise", "Promise") == ("Promise", "Promise", "Promise")
    assert _names(base + "Global_Objects/Intl/DateTimeFormat/format", "Intl.DateTimeFormat.prototype.format()") == (
        "Intl.DateTimeFormat", "format", "Intl.DateTimeFormat.prototype.format")
    assert _names(base + "Statements/for...of", "for...of") == ("statements", "for...of", "for...of")


def test_macros_and_links():
    assert clean('{{jsxref("Array/forEach")}} and {{Glossary("Iterator", "iterators")}}') == "`Array.forEach` and iterators"
    assert clean("[text](/en-US/docs/x) {{Deprecated_Header}}") == "text"
    assert parse_parameters("- `a`\n  - : First.\n    continued\n- `b`\n  - : Second.") == [("a", "First. continued"), ("b", "Second.")]
