"""A saved, reusable candidate profile — set up once, used by every search."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

PROFILE_PATH = "profile.json"


@dataclass
class Profile:
    max_commute_miles: Optional[int] = None
    remote_ok: bool = True
    willing_to_relocate: bool = False
    salary_min_override: Optional[int] = None
    excluded_companies: list[str] = field(default_factory=list)
    notes: Optional[str] = None


def load_profile(path: str = PROFILE_PATH) -> Optional[Profile]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Profile(**data)


def save_profile(profile: Profile, path: str = PROFILE_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, indent=2)
