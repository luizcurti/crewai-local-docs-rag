import argparse

import pytest

from ingest import source_names


def test_sources_are_validated():
    assert source_names("mdn,python") == ["mdn", "python"]
    with pytest.raises(argparse.ArgumentTypeError, match="unknown source.*foo"):
        source_names("mdn,foo")
