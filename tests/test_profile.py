from profile import Profile, load_profile, save_profile


def test_load_profile_returns_none_when_missing(tmp_path):
    path = tmp_path / "profile.json"
    assert load_profile(str(path)) is None


def test_save_and_load_profile_round_trips(tmp_path):
    path = tmp_path / "profile.json"
    profile = Profile(
        max_commute_miles=20,
        remote_ok=False,
        willing_to_relocate=True,
        salary_min_override=100000,
        excluded_companies=["Acme", "Globex"],
        notes="Prefers contract roles",
    )

    save_profile(profile, str(path))
    loaded = load_profile(str(path))

    assert loaded == profile


def test_profile_defaults():
    profile = Profile()

    assert profile.max_commute_miles is None
    assert profile.remote_ok is True
    assert profile.willing_to_relocate is False
    assert profile.salary_min_override is None
    assert profile.excluded_companies == []
    assert profile.notes is None
