from unittest.mock import Mock

from adzuna_search import JobListing
from find_jobs import (
    DEFAULT_DISTANCE_MILES,
    GOOGLE_JOBS_MAX_TITLES,
    AdzunaSource,
    GoogleJobsSource,
    dedupe,
    filter_excluded_companies,
    resolve_country,
    resolve_distance,
    resolve_location,
    resolve_salary_min,
    titles_for_source,
)


def _job(job_id, source="adzuna", company="Acme"):
    return JobListing(
        title="Engineer",
        company=company,
        location="Remote",
        salary_min=100000,
        salary_max=120000,
        created="2026-01-01T00:00:00Z",
        url=f"https://example.com/{job_id}",
        description="desc",
        id=job_id,
        source=source,
    )


def test_dedupe_removes_same_source_duplicates():
    jobs = [_job("1"), _job("2"), _job("1")]

    result = dedupe(jobs)

    assert [j.id for j in result] == ["1", "2"]


def test_dedupe_keeps_first_seen_order():
    jobs = [_job("2"), _job("1"), _job("2")]

    result = dedupe(jobs)

    assert [j.id for j in result] == ["2", "1"]


def test_dedupe_does_not_collide_ids_across_sources():
    jobs = [_job("1", source="adzuna"), _job("1", source="google_jobs")]

    result = dedupe(jobs)

    assert len(result) == 2


def test_filter_excluded_companies_removes_matches_case_insensitively():
    jobs = [_job("1", company="MegaCorp"), _job("2", company="Acme")]

    result = filter_excluded_companies(jobs, ["megacorp"])

    assert [j.id for j in result] == ["2"]


def test_filter_excluded_companies_no_exclusions_returns_all():
    jobs = [_job("1"), _job("2")]

    result = filter_excluded_companies(jobs, [])

    assert result == jobs


def test_resolve_location_prefers_cli_value():
    assert resolve_location("Austin", "Seattle") == "Austin"


def test_resolve_location_falls_back_to_suggestion():
    assert resolve_location(None, "Seattle") == "Seattle"


def test_resolve_salary_min_prefers_cli_value_including_zero():
    assert resolve_salary_min(0, 100000, 90000) == 0


def test_resolve_salary_min_falls_back_to_profile():
    assert resolve_salary_min(None, 100000, 90000) == 100000


def test_resolve_salary_min_falls_back_to_suggestion_when_no_profile():
    assert resolve_salary_min(None, None, 90000) == 90000


def test_resolve_country_prefers_cli_value():
    assert resolve_country("us", "gb") == "us"


def test_resolve_country_falls_back_to_suggestion():
    assert resolve_country(None, "gb") == "gb"


def test_resolve_country_defaults_to_us():
    assert resolve_country(None, None) == "us"


def test_resolve_distance_prefers_cli_value():
    assert resolve_distance(50, 20) == 50


def test_resolve_distance_falls_back_to_profile():
    assert resolve_distance(None, 20) == 20


def test_resolve_distance_falls_back_to_default():
    assert resolve_distance(None, None) == DEFAULT_DISTANCE_MILES


def test_titles_for_source_caps_google_jobs():
    titles = [f"Title {i}" for i in range(GOOGLE_JOBS_MAX_TITLES + 3)]
    source = GoogleJobsSource("fake-key")

    assert titles_for_source(source, titles) == titles[:GOOGLE_JOBS_MAX_TITLES]


def test_titles_for_source_does_not_cap_other_sources():
    titles = [f"Title {i}" for i in range(GOOGLE_JOBS_MAX_TITLES + 3)]
    source = AdzunaSource("id", "key", "us")

    assert titles_for_source(source, titles) == titles


def test_google_jobs_source_filters_by_salary_min_client_side(monkeypatch):
    jobs = [
        JobListing(title="A", company="Acme", location="X", salary_min=60000, salary_max=70000,
                   created="", url="u1", description="", id="1", source="google_jobs"),
        JobListing(title="B", company="Acme", location="X", salary_min=30000, salary_max=40000,
                   created="", url="u2", description="", id="2", source="google_jobs"),
        JobListing(title="C", company="Acme", location="X", salary_min=None, salary_max=None,
                   created="", url="u3", description="", id="3", source="google_jobs"),
    ]
    monkeypatch.setattr("find_jobs.google_jobs_search_jobs", lambda *a, **kw: jobs)

    source = GoogleJobsSource("fake-key")
    result = source.search("engineer", 50000, "London", 10)

    # keeps the job above the floor and the job with unknown salary; drops the one below
    assert {j.id for j in result} == {"1", "3"}
