import types
from unittest.mock import Mock

from adzuna_search import JobListing
from job_scoring import MAX_JOBS_TO_SCORE, score_jobs
from profile import Profile


def _job(job_id, title="Engineer", source="adzuna"):
    return JobListing(
        title=title,
        company="Acme",
        location="Remote",
        salary_min=100000,
        salary_max=120000,
        created="2026-01-01T00:00:00Z",
        url=f"https://example.com/{job_id}",
        description="desc",
        id=job_id,
        source=source,
    )


def _fake_client(scores):
    block = types.SimpleNamespace(type="tool_use", input={"scores": scores})
    response = types.SimpleNamespace(content=[block])
    client = Mock()
    client.messages.create.return_value = response
    return client


def test_score_jobs_returns_empty_for_no_listings():
    assert score_jobs("cv text", [], "fake-key") == []


def test_score_jobs_sorts_by_score_descending(monkeypatch):
    jobs = [_job("1"), _job("2"), _job("3")]
    scores = [
        {"index": 0, "score": 50, "rationale": "ok"},
        {"index": 1, "score": 90, "rationale": "great"},
        {"index": 2, "score": 10, "rationale": "poor"},
    ]
    monkeypatch.setattr("job_scoring.anthropic.Anthropic", lambda api_key: _fake_client(scores))

    scored = score_jobs("cv text", jobs, "fake-key")

    assert [sj.job.id for sj in scored] == ["2", "1", "3"]
    assert scored[0].score == 90
    assert scored[0].rationale == "great"


def test_score_jobs_skips_listings_without_a_score(monkeypatch):
    jobs = [_job("1"), _job("2")]
    scores = [{"index": 0, "score": 70, "rationale": "fine"}]
    monkeypatch.setattr("job_scoring.anthropic.Anthropic", lambda api_key: _fake_client(scores))

    scored = score_jobs("cv text", jobs, "fake-key")

    assert len(scored) == 1
    assert scored[0].job.id == "1"


def test_score_jobs_correlates_by_position_not_id(monkeypatch):
    # two jobs from different sources sharing the same raw id — position-based
    # correlation means this can't collide, unlike the old id-echo scheme.
    jobs = [_job("1", source="adzuna"), _job("1", source="google_jobs")]
    scores = [
        {"index": 0, "score": 90, "rationale": "adzuna fit"},
        {"index": 1, "score": 40, "rationale": "google jobs fit"},
    ]
    monkeypatch.setattr("job_scoring.anthropic.Anthropic", lambda api_key: _fake_client(scores))

    scored = score_jobs("cv text", jobs, "fake-key")

    by_source = {sj.job.source: sj for sj in scored}
    assert by_source["adzuna"].score == 90
    assert by_source["google_jobs"].score == 40


def test_score_jobs_never_sends_long_opaque_ids_to_claude(monkeypatch):
    # Google Jobs ids are 300+ char base64 blobs — echoing them back per job
    # in a large batch can exhaust max_tokens before all scores are written.
    # Correlation must use a short positional index instead.
    long_id = "eyJqb2JfdGl0bGUi" * 30
    jobs = [_job(long_id, source="google_jobs")]
    captured = {}

    def fake_create(**kwargs):
        captured["content"] = kwargs["messages"][0]["content"]
        block = types.SimpleNamespace(type="tool_use", input={"scores": [{"index": 0, "score": 80, "rationale": "ok"}]})
        return types.SimpleNamespace(content=[block])

    client = Mock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr("job_scoring.anthropic.Anthropic", lambda api_key: client)

    scored = score_jobs("cv text", jobs, "fake-key")

    assert long_id not in captured["content"]
    assert len(scored) == 1
    assert scored[0].score == 80


def test_score_jobs_includes_profile_preferences_in_prompt(monkeypatch):
    jobs = [_job("1")]
    captured = {}

    def fake_create(**kwargs):
        captured["content"] = kwargs["messages"][0]["content"]
        block = types.SimpleNamespace(type="tool_use", input={"scores": [{"index": 0, "score": 50, "rationale": "ok"}]})
        return types.SimpleNamespace(content=[block])

    client = Mock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr("job_scoring.anthropic.Anthropic", lambda api_key: client)

    profile = Profile(max_commute_miles=15, remote_ok=False, willing_to_relocate=True, notes="Prefers startups")
    score_jobs("cv text", jobs, "fake-key", profile=profile)

    assert "15 miles" in captured["content"]
    assert "Prefers startups" in captured["content"]


def test_score_jobs_batches_large_result_sets_instead_of_dropping_them(monkeypatch):
    total = MAX_JOBS_TO_SCORE + 10
    jobs = [_job(str(i), title=f"Job{i}") for i in range(total)]
    calls = []

    def fake_create(**kwargs):
        content = kwargs["messages"][0]["content"]
        # titles are globally unique across the whole job set, unlike indices
        # (which restart at 0 in every batch) — count those to find batch size.
        batch_size = sum(1 for i in range(total) if f"'title': 'Job{i}'" in content)
        calls.append(batch_size)
        scores = [{"index": i, "score": 50, "rationale": "ok"} for i in range(batch_size)]
        block = types.SimpleNamespace(type="tool_use", input={"scores": scores})
        return types.SimpleNamespace(content=[block])

    client = Mock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr("job_scoring.anthropic.Anthropic", lambda api_key: client)

    scored = score_jobs("cv text", jobs, "fake-key")

    # every job scored — none silently dropped — across more than one batch
    assert len(scored) == total
    assert len(calls) == 2
    assert calls[0] == MAX_JOBS_TO_SCORE
    assert calls[1] == total - MAX_JOBS_TO_SCORE
