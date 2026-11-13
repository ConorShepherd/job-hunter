from unittest.mock import Mock

import pytest

from adzuna_search import AdzunaError, JobListing, search_jobs


def _job(job_id, title="Engineer"):
    return {
        "id": job_id,
        "title": title,
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Remote"},
        "salary_min": 100000,
        "salary_max": 120000,
        "created": "2026-01-01T00:00:00Z",
        "redirect_url": f"https://example.com/{job_id}",
        "description": "desc",
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
        "adzuna_search.requests.get",
        lambda url, params, timeout: _resp(json_data={"count": 1, "results": [_job("1")]}),
    )

    listings = search_jobs("id", "key", "engineer", max_results=5)

    assert len(listings) == 1
    job = listings[0]
    assert isinstance(job, JobListing)
    assert job.id == "1"
    assert job.source == "adzuna"
    assert job.company == "Acme"
    assert job.location == "Remote"


def test_search_jobs_omits_optional_params_when_not_given(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _resp(json_data={"count": 0, "results": []})

    monkeypatch.setattr("adzuna_search.requests.get", fake_get)
    search_jobs("id", "key", "engineer")

    assert "salary_min" not in captured["params"]
    assert "where" not in captured["params"]


def test_search_jobs_includes_optional_params_when_given(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured["params"] = params
        return _resp(json_data={"count": 0, "results": []})

    monkeypatch.setattr("adzuna_search.requests.get", fake_get)
    search_jobs("id", "key", "engineer", salary_min=100000, location="Austin")

    assert captured["params"]["salary_min"] == 100000
    assert captured["params"]["where"] == "Austin"


def test_search_jobs_paginates_until_max_results(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(url)
        page = int(url.rsplit("/", 1)[-1])
        if page == 1:
            jobs = [_job(str(i)) for i in range(20)]
        else:
            jobs = [_job(str(i)) for i in range(20, 25)]
        return _resp(json_data={"count": 25, "results": jobs})

    monkeypatch.setattr("adzuna_search.requests.get", fake_get)
    listings = search_jobs("id", "key", "engineer", max_results=25, results_per_page=20)

    assert len(listings) == 25
    assert len(calls) == 2


def test_search_jobs_stops_when_no_results(monkeypatch):
    monkeypatch.setattr(
        "adzuna_search.requests.get",
        lambda url, params, timeout: _resp(json_data={"count": 0, "results": []}),
    )

    listings = search_jobs("id", "key", "engineer", max_results=10)

    assert listings == []


def test_search_jobs_caps_at_max_results(monkeypatch):
    monkeypatch.setattr(
        "adzuna_search.requests.get",
        lambda url, params, timeout: _resp(
            json_data={"count": 20, "results": [_job(str(i)) for i in range(20)]}
        ),
    )

    listings = search_jobs("id", "key", "engineer", max_results=3, results_per_page=20)

    assert len(listings) == 3


def test_search_jobs_raises_on_401(monkeypatch):
    monkeypatch.setattr(
        "adzuna_search.requests.get",
        lambda url, params, timeout: _resp(status_code=401, text="unauthorized"),
    )

    with pytest.raises(AdzunaError, match="401"):
        search_jobs("id", "key", "engineer")


def test_search_jobs_raises_on_other_error(monkeypatch):
    monkeypatch.setattr(
        "adzuna_search.requests.get",
        lambda url, params, timeout: _resp(status_code=500, text="server error"),
    )

    with pytest.raises(AdzunaError, match="500"):
        search_jobs("id", "key", "engineer")
