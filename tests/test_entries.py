from entries import ApiEntry, CodeExample, assign_ids, split_output, to_chunks


def entry(**kw):
    base = dict(language="javascript", runtime="ecmascript", module="Array", object="Array", name="map",
                full_name="Array.prototype.map", kind="method", url="https://x/map")
    return ApiEntry(**{**base, **kw})


def test_ids_follow_language_object_and_name():
    entries = [entry(), entry(runtime="nodejs", module="buffer", object="Buffer", name="from", full_name="Buffer.from"),
               entry(runtime="nodejs", module="buffer", object="Buffer", name="from", full_name="Buffer.from"),
               entry(language="python", runtime="cpython", module="builtins", object="builtins", name="map", full_name="map"),
               entry(runtime="nodejs", module="fs", object="fs", name="fs", full_name="fs", kind="module")]
    assign_ids(entries)
    assert [e.id for e in entries] == [
        "javascript_array_map", "nodejs_buffer_from", "nodejs_buffer_from_2", "python_builtins_map", "nodejs_fs"]


def test_function_and_example_chunks():
    e = entry(description="Creates a new array.", parameters=[("callbackFn", "A function.")], returns="A new array.",
              examples=[CodeExample("Doubling", "[1, 2].map((x) => x * 2);", "js", "[2, 4]")])
    assign_ids([e])
    function, example = to_chunks(e)
    assert function["id"] == "javascript_array_map"
    assert function["metadata"]["type"] == "function" and function["metadata"]["examples"] == 1
    assert function["metadata"]["name_lower"] == "map"
    assert "Parameters:\n- callbackFn: A function." in function["text"]
    assert "Returns:\nA new array." in function["text"]
    assert example["id"] == "javascript_array_map_example_01"
    assert example["metadata"]["function_id"] == "javascript_array_map"
    assert example["metadata"]["code"] == "[1, 2].map((x) => x * 2);"
    assert "Expected output:\n[2, 4]" in example["text"]


def test_split_output():
    code, output = split_output("console.log(1);\n// Expected output: 1\nprint(2)  \n# Prints: 2")
    assert code == "console.log(1);\nprint(2)  "
    assert output == "1\n2"


def test_short_title():
    from entries import short_title

    assert short_title("A common use case is to read a file. The easiest way is:") == "A common use case is to read a file"
    assert short_title('* "zip()" can be used to unzip a list:') == '"zip()" can be used to unzip a list'
