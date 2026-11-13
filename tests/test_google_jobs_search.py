from unittest.mock import Mock

import pytest

from google_jobs_search import GoogleJobsError, _resolve_location, search_jobs


@pytest.fixture(autouse=True)
def _clear_location_cache():
    _resolve_location.cache_clear()
    yield
    _resolve_location.cache_clear()


def _job(job_id, title="Engineer", apply_link="https://example.com/apply"):
    return {
        "job_id": job_id,
        "title": title,
        "company_name": "Acme",
        "location": "London, UK",
        "description": "desc",
        "detected_extensions": {"posted_at": "2 days ago"},
        "apply_options": [{"title": "Indeed", "link": apply_link}],
    }


def _resp(status_code=200, json_data=None, text=""):
    resp = Mock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def test_search_jobs_parses_listing_fields(monkeypatch):
    monkeypatch.setattr(
        "google_jobs_search.requests.get",
        lambda url, params, timeout: _resp(json_data={"jobs_results": [_job("abc123")]}),
    )

    listings = search_jobs("key", "engineer", max_results=5)

    assert len(listings) == 1
    job = listings[0]
    assert job.id == "abc123"
    assert job.source == "google_jobs"
    assert job.company == "Acme"
    assert job.url == "https://example.com/apply"
    assert job.salary_min is None  # no reliable structured salary from this engine


def test_search_jobs_falls_back_to_share_link_when_no_apply_options(monkeypatch):
    job = _job("abc123")
    job["apply_options"] = []
    job["share_link"] = "https://google.com/jobs/abc123"

    monkeypatch.setattr(
        "google_jobs_search.requests.get",
        lambda url, params, timeout: _resp(json_data={"jobs_results": [job]}),
    )

    listings = search_jobs("key", "engineer")

    assert listings[0].url == "https://google.com/jobs/abc123"


def test_search_jobs_converts_distance_miles_to_km(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _resp(json_data={"jobs_results": []})

    monkeypatch.setattr("google_jobs_search.requests.get", fake_get)
    search_jobs("key", "engineer", distance=10)

    assert captured["params"]["lrad"] == 16  # 10 miles ≈ 16 km


def test_search_jobs_paginates_via_next_page_token(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params.get("next_page_token"))
        if params.get("next_page_token") is None:
            return _resp(json_data={
                "jobs_results": [_job(str(i)) for i in range(10)],
                "serpapi_pagination": {"next_page_token": "TOKEN123"},
            })
        return _resp(json_data={"jobs_results": [_job(str(i)) for i in range(10, 15)]})

    monkeypatch.setattr("google_jobs_search.requests.get", fake_get)
    listings = search_jobs("key", "engineer", max_results=15)

    assert len(listings) == 15
    assert calls == [None, "TOKEN123"]


def test_search_jobs_stops_when_no_results(monkeypatch):
    monkeypatch.setattr(
        "google_jobs_search.requests.get",
        lambda url, params, timeout: _resp(json_data={"jobs_results": []}),
    )

    assert search_jobs("key", "engineer") == []


def test_search_jobs_raises_on_401(monkeypatch):
    monkeypatch.setattr(
        "google_jobs_search.requests.get",
        lambda url, params, timeout: _resp(status_code=401, text="unauthorized"),
    )

    with pytest.raises(GoogleJobsError, match="401"):
        search_jobs("key", "engineer")


def test_search_jobs_raises_on_embedded_error(monkeypatch):
    monkeypatch.setattr(
        "google_jobs_search.requests.get",
        lambda url, params, timeout: _resp(json_data={"error": "Invalid API key."}),
    )

    with pytest.raises(GoogleJobsError, match="Invalid API key"):
        search_jobs("key", "engineer")


def test_resolve_location_uses_canonical_name(monkeypatch):
    captured = {}
    # first locations.json call (full string) returns no match, second (first segment) does
    calls = {"n": 0}

    def fake_get(url, params, timeout):
        if "locations.json" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                return _resp(json_data=[])
            assert params["q"] == "Cheltenham"
            return _resp(json_data=[{"canonical_name": "Cheltenham,England,United Kingdom"}])
        captured["params"] = params
        return _resp(json_data={"jobs_results": []})

    monkeypatch.setattr("google_jobs_search.requests.get", fake_get)
    search_jobs("key", "engineer", location="Cheltenham, Gloucestershire")

    assert captured["params"]["location"] == "Cheltenham,England,United Kingdom"


def test_resolve_location_omits_param_when_nothing_matches(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        if "locations.json" in url:
            return _resp(json_data=[])
        captured["params"] = params
        return _resp(json_data={"jobs_results": []})

    monkeypatch.setattr("google_jobs_search.requests.get", fake_get)
    search_jobs("key", "engineer", location="Nowhere, Fictional County")

    assert "location" not in captured["params"]


def test_resolve_location_caches_repeat_lookups(monkeypatch):
    lookups = []

    def fake_get(url, params, timeout):
        if "locations.json" in url:
            lookups.append(params["q"])
            return _resp(json_data=[{"canonical_name": "London,England,United Kingdom"}])
        return _resp(json_data={"jobs_results": []})

    monkeypatch.setattr("google_jobs_search.requests.get", fake_get)
    search_jobs("key", "engineer", location="London")
    search_jobs("key", "designer", location="London")

    assert lookups == ["London"]  # second call hit the cache, not the network
