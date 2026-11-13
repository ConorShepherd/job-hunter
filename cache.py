"""Local disk caches that skip repeat Claude calls for unchanged CVs and already-scored jobs."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from typing import Optional

from cv_extraction import JobCriteria

CACHE_DIR = ".cache"
CRITERIA_DIR = os.path.join(CACHE_DIR, "cv_criteria")
SCORES_DIR = os.path.join(CACHE_DIR, "scores")


def cv_text_hash(cv_text: str, notes: Optional[str] = None) -> str:
    """Hash the CV text plus any profile notes, since notes shape both extraction and scoring."""
    combined = cv_text if not notes else f"{cv_text}\n---PROFILE NOTES---\n{notes}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _read_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_cached_criteria(cv_hash: str) -> Optional[JobCriteria]:
    data = _read_json(os.path.join(CRITERIA_DIR, f"{cv_hash}.json"))
    return JobCriteria(**data) if data is not None else None


def save_cached_criteria(cv_hash: str, criteria: JobCriteria) -> None:
    os.makedirs(CRITERIA_DIR, exist_ok=True)
    with open(os.path.join(CRITERIA_DIR, f"{cv_hash}.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(criteria), f, indent=2)


def load_score_cache(cv_hash: str) -> dict:
    return _read_json(os.path.join(SCORES_DIR, f"{cv_hash}.json")) or {}


def save_score_cache(cv_hash: str, scores: dict) -> None:
    os.makedirs(SCORES_DIR, exist_ok=True)
    with open(os.path.join(SCORES_DIR, f"{cv_hash}.json"), "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2)
