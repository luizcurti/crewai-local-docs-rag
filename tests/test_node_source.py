from sources.node import BASE_URL, parse_module, parse_parameters, slugify

PAGE = '''# File system

<!--introduced_in=v0.10.0-->

> Stability: 2 - Stable

The `node:fs` module enables interacting with the file system.

```mjs
import * as fs from 'node:fs/promises';
```

```cjs
const fs = require('node:fs/promises');
```

## Promise example

Promise-based operations return a promise:

```mjs
import { unlink } from 'node:fs/promises';
await unlink('/tmp/hello');
```

## Class: `FileHandle`

A {FileHandle} object is an object wrapper for a numeric file descriptor.

### Event: `'close'`

Emitted when the file handle has been closed.

### `filehandle.read(buffer, offset)`

* `buffer` {Buffer} A buffer that will be filled.
* `offset` {integer} The location in the buffer.
* Returns: {Promise} Fulfills upon success.

Reads data from the file.

## `fs.readFile(path[, options], callback)`

<!-- YAML
added: v0.1.29
-->

* `path` {string|Buffer|URL|integer} filename or file descriptor
* `options` {Object|string}
  * `encoding` {string|null} **Default:** `null`
* `callback` {Function}

Asynchronously reads the entire contents of a file. See [`fs.stat()`][].

```mjs
import { readFile } from 'node:fs';

readFile('/etc/passwd', (err, data) => {
  console.log(data); // Prints: <Buffer ...>
});
```

An example using the `buffer` option:

```js
readFile('a.txt', { buffer }, () => {});
```

### Static method: `Buffer.from(array)`

Allocates a new Buffer.

## `--env-file=file`

A command-line option, not an API.
'''


def entries():
    return {e.full_name: e for e in parse_module("fs", PAGE)}


def test_module_entry_and_prose_examples():
    fs = entries()["fs"]
    assert (fs.kind, fs.url) == ("module", f"{BASE_URL}/fs.html")
    assert fs.description == "The `node:fs` module enables interacting with the file system."
    assert "Stability: 2 - Stable" in fs.notes
    # The mjs/cjs twin is kept once; the "Promise example" section belongs to the module.
    assert [ex.code.splitlines()[0] for ex in fs.examples] == [
        "import * as fs from 'node:fs/promises';", "import { unlink } from 'node:fs/promises';"]
    assert fs.examples[1].title == "Promise-based operations return a promise"


def test_function_entry():
    e = entries()["fs.readFile"]
    assert (e.module, e.object, e.name, e.kind) == ("fs", "fs", "readFile", "function")
    assert e.signature == "fs.readFile(path[, options], callback)"
    assert e.url.endswith("fs.html#fsreadfilepath-options-callback")
    assert e.parameters[0] == ("path", "{string|Buffer|URL|integer} filename or file descriptor")
    assert e.parameters[1] == ("options", "{Object|string}; encoding {string|null} **Default:** null")
    assert e.notes == "Added in: v0.1.29"
    assert e.description == "Asynchronously reads the entire contents of a file. See `fs.stat()`."
    first = e.examples[0]
    assert first.output == "<Buffer ...>" and "Prints" not in first.code
    assert e.examples[1].title == "An example using the `buffer` option"


def test_class_members_belong_to_the_class():
    found = entries()
    method = found["filehandle.read"]
    assert (method.object, method.name, method.kind) == ("FileHandle", "read", "method")
    assert method.returns == "{Promise} Fulfills upon success."
    assert [p[0] for p in method.parameters] == ["buffer", "offset"]
    event = found["FileHandle event 'close'"]
    assert (event.kind, event.object, event.name) == ("event", "FileHandle", "close")
    assert found["FileHandle"].kind == "class"
    assert found["Buffer.from"].kind == "static method"
    assert "--env-file=file" not in found


def test_parameters_and_slug():
    params, returns = parse_parameters("* `a` {string} first\n  more text\n* Returns: {boolean}\n\nText.")
    assert params == [("a", "{string} first more text")]
    assert returns == "{boolean}"
    assert slugify("fs.readFile(path[, options])") == "fsreadfilepath-options"
