"""The web UI renders, and explains what is missing, when Ollama is not running."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

import preflight

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_ui_without_ollama(monkeypatch):
    monkeypatch.setattr(preflight, "OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens there
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Ollama is not reachable" in e.value for e in at.sidebar.error)
    assert at.button[0].label == "Ask" and at.button[0].disabled
    assert [t.label for t in at.tabs] == ["Ask", "Vector database"]
