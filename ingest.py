"""Builds the vector database: download -> parse -> function/example chunks -> embeddings -> Chroma.

Usage:
    python ingest.py                     # every source (MDN, Node.js, Python)
    python ingest.py --sources mdn,node  # only some sources (the others are kept)
    python ingest.py --reset             # drop the whole collection first
"""

import argparse
import time
from collections import Counter

from entries import assign_ids, to_chunks
from sources import SOURCES
from store import DOC_PREFIX, embed, get_collection, mark_ingest

BATCH = 64


def source_names(value: str) -> list[str]:
    names = value.split(",")
    if unknown := [n for n in names if n not in SOURCES]:
        raise argparse.ArgumentTypeError(f"unknown source(s): {', '.join(unknown)} (choose from {', '.join(SOURCES)})")
    return names


def main():
    from preflight import check_services

    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=source_names, default=list(SOURCES), help=f"comma-separated: {', '.join(SOURCES)}")
    parser.add_argument("--reset", action="store_true", help="drop the whole collection first")
    args = parser.parse_args()
    check_services(need_index=False, need_llm=False)

    names = args.sources
    entries = []
    for name in names:
        source = SOURCES[name]
        start = time.monotonic()
        loaded = source.load_all()
        print(f"{source.LABEL} {source.version()}: {len(loaded)} API entries, "
              f"{sum(len(e.examples) for e in loaded)} examples ({time.monotonic() - start:.0f}s)", flush=True)
        entries += loaded
    # IDs are assigned over every source at once so they stay unique.
    assign_ids(entries)
    chunks = [c for e in entries for c in to_chunks(e)]

    # Until this ingestion finishes, start.sh treats the database as incomplete and runs it again.
    mark_ingest(complete=False)
    collection = get_collection(reset=args.reset)
    runtimes = [SOURCES[name].RUNTIME for name in names]
    old_ids = set(collection.get(where={"runtime": {"$in": runtimes}}, include=[])["ids"])

    # Re-indexing a source replaces it: the new records first, then the old ones that are
    # gone, so an ingestion that stops halfway never leaves a source without records.
    start = time.monotonic()
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        collection.upsert(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
            embeddings=embed([c["text"] for c in batch], DOC_PREFIX),
        )
        done = i + len(batch)
        if done % (BATCH * 20) < BATCH or done == len(chunks):
            rate = done / (time.monotonic() - start)
            print(f"  embedded {done}/{len(chunks)} chunks ({rate:.0f}/s)", flush=True)

    stale = list(old_ids - {c["id"] for c in chunks})
    for i in range(0, len(stale), 5000):
        collection.delete(ids=stale[i : i + 5000])
    mark_ingest(complete=True)

    counts = Counter(f"{c['metadata']['runtime']}/{c['metadata']['type']}" for c in chunks)
    print("Indexed:", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print(f"Done: {collection.count()} records in the collection.")


if __name__ == "__main__":
    main()
