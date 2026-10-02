"""Documentation sources. Each one exposes NAME, LABEL, RUNTIME (a key of languages.RUNTIMES),
version() and load_all() -> list[ApiEntry].

    mdn    - the JavaScript language (Array.prototype.map, Promise, for...of)
    node   - the Node.js runtime APIs (fs, http, path)
    python - the Python standard library (map, str.split, pathlib)
"""

from sources import mdn, node, python

SOURCES = {s.NAME: s for s in (mdn, node, python)}
