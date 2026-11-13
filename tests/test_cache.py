import os

import cache
from cv_extraction import JobCriteria


def test_cv_text_hash_is_deterministic():
    assert cache.cv_text_hash("hello") == cache.cv_text_hash("hello")
    assert cache.cv_text_hash("hello") != cache.cv_text_hash("world")


def test_cv_text_hash_changes_when_notes_change():
    base = cache.cv_text_hash("hello")
    with_notes = cache.cv_text_hash("hello", "prefers remote roles")
    different_notes = cache.cv_text_hash("hello", "open to relocation")

    assert with_notes != base
    assert with_notes != different_notes


def test_cv_text_hash_same_notes_same_hash():
    assert cache.cv_text_hash("hello", "same notes") == cache.cv_text_hash("hello", "same notes")


def test_criteria_cache_miss_then_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CRITERIA_DIR", str(tmp_path / "cv_criteria"))

    h = cache.cv_text_hash("some cv text")
    assert cache.load_cached_criteria(h) is None

    criteria = JobCriteria(
        titles=["Engineer"], suggested_location="London", suggested_country="gb", suggested_salary_min=90000
    )
    cache.save_cached_criteria(h, criteria)

    assert cache.load_cached_criteria(h) == criteria


def test_score_cache_miss_then_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "SCORES_DIR", str(tmp_path / "scores"))

    h = "somehash"
    assert cache.load_score_cache(h) == {}

    cache.save_score_cache(h, {"adzuna:1": {"score": 80, "rationale": "good fit"}})

    assert cache.load_score_cache(h) == {"adzuna:1": {"score": 80, "rationale": "good fit"}}


def test_corrupt_criteria_cache_file_treated_as_miss(tmp_path, monkeypatch):
    criteria_dir = tmp_path / "cv_criteria"
    criteria_dir.mkdir()
    monkeypatch.setattr(cache, "CRITERIA_DIR", str(criteria_dir))

    h = "badhash"
    (criteria_dir / f"{h}.json").write_text("not valid json{{{", encoding="utf-8")

    assert cache.load_cached_criteria(h) is None


def test_corrupt_score_cache_file_treated_as_empty(tmp_path, monkeypatch):
    scores_dir = tmp_path / "scores"
    scores_dir.mkdir()
    monkeypatch.setattr(cache, "SCORES_DIR", str(scores_dir))

    h = "badhash"
    (scores_dir / f"{h}.json").write_text("not valid json{{{", encoding="utf-8")

    assert cache.load_score_cache(h) == {}
