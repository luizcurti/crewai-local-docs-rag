import os
import time

import answer_cache


def use_tmp_cache(monkeypatch, tmp_path, ttl=3600):
    monkeypatch.setattr(answer_cache, "ANSWER_CACHE_DIR", tmp_path)
    monkeypatch.setattr(answer_cache, "ANSWER_CACHE_TTL", ttl)


def test_normalize():
    assert answer_cache.normalize("  What is  map used for?? ") == "What is map used for"
    assert answer_cache.normalize("What is Map?") != answer_cache.normalize("What is map used for?")


def test_case_is_kept_because_map_is_not_Map(monkeypatch, tmp_path):
    use_tmp_cache(monkeypatch, tmp_path)
    answer_cache.put("What is map used for?", "1", {"answer": "Array.prototype.map"})
    assert answer_cache.get("What is Map used for?", "1") is None


def test_same_question_same_model_and_index(monkeypatch, tmp_path):
    use_tmp_cache(monkeypatch, tmp_path)
    answer_cache.put("What is map used for?", "22421", {"answer": "cached"})
    assert answer_cache.get("What is map used for", "22421") == {"answer": "cached"}
    assert answer_cache.get("What is map used for", "22500") is None  # re-indexed
    monkeypatch.setattr(answer_cache, "LLM_MODEL", "another-model")
    assert answer_cache.get("What is map used for", "22421") is None  # another model


def test_expired_answers_are_deleted(monkeypatch, tmp_path):
    use_tmp_cache(monkeypatch, tmp_path, ttl=-1)
    answer_cache.put("What is map used for?", "1", {"answer": "old"})
    assert answer_cache.get("What is map used for?", "1") is None
    assert list(tmp_path.glob("*.json")) == []


def test_clear(monkeypatch, tmp_path):
    use_tmp_cache(monkeypatch, tmp_path)
    answer_cache.put("a", "1", {}), answer_cache.put("b", "1", {})
    assert answer_cache.clear() == 2 and answer_cache.get("a", "1") is None


def test_saving_deletes_expired_answers_of_other_questions(monkeypatch, tmp_path):
    use_tmp_cache(monkeypatch, tmp_path)
    answer_cache.put("never asked again", "1", {})
    old = next(tmp_path.glob("*.json"))
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    answer_cache.put("a new question", "1", {})
    assert not old.exists() and len(list(tmp_path.glob("*.json"))) == 1
