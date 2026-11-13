import types
from unittest.mock import Mock

import anthropic
import pytest

from cv_extraction import CVExtractionError, extract_job_criteria


def _fake_client(tool_input):
    block = types.SimpleNamespace(type="tool_use", input=tool_input)
    response = types.SimpleNamespace(content=[block])
    client = Mock()
    client.messages.create.return_value = response
    return client


def test_extract_job_criteria_parses_all_fields(monkeypatch):
    tool_input = {
        "titles": ["Engineer", "Architect"],
        "suggested_location": "London",
        "suggested_country": "gb",
        "suggested_salary_min": 90000,
    }
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: _fake_client(tool_input))

    criteria = extract_job_criteria("cv text", "fake-key")

    assert criteria.titles == ["Engineer", "Architect"]
    assert criteria.suggested_location == "London"
    assert criteria.suggested_country == "gb"
    assert criteria.suggested_salary_min == 90000


def test_extract_job_criteria_caps_titles(monkeypatch):
    tool_input = {"titles": [f"Title {i}" for i in range(10)]}
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: _fake_client(tool_input))

    criteria = extract_job_criteria("cv text", "fake-key", max_titles=3)

    assert len(criteria.titles) == 3


def test_extract_job_criteria_raises_when_no_titles(monkeypatch):
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: _fake_client({"titles": []}))

    with pytest.raises(CVExtractionError, match="did not return any job titles"):
        extract_job_criteria("cv text", "fake-key")


def test_extract_job_criteria_includes_notes_in_prompt(monkeypatch):
    captured = {}
    response = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", input={"titles": ["Engineer"]})]
    )

    def fake_create(**kwargs):
        captured["content"] = kwargs["messages"][0]["content"]
        return response

    client = Mock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: client)

    extract_job_criteria("cv text", "fake-key", notes="Keen to leverage my CFA designation")

    assert "Keen to leverage my CFA designation" in captured["content"]


def test_extract_job_criteria_omits_notes_section_when_absent(monkeypatch):
    captured = {}
    response = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", input={"titles": ["Engineer"]})]
    )

    def fake_create(**kwargs):
        captured["content"] = kwargs["messages"][0]["content"]
        return response

    client = Mock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: client)

    extract_job_criteria("cv text", "fake-key")

    assert "Additional guidance" not in captured["content"]


def test_extract_job_criteria_tells_model_the_requested_max_titles(monkeypatch):
    captured = {}
    response = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="tool_use", input={"titles": ["Engineer"]})]
    )

    def fake_create(**kwargs):
        captured["tools"] = kwargs["tools"]
        return response

    client = Mock()
    client.messages.create.side_effect = fake_create
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: client)

    extract_job_criteria("cv text", "fake-key", max_titles=15)

    titles_description = captured["tools"][0]["input_schema"]["properties"]["titles"]["description"]
    assert "15" in titles_description
    assert "6" not in titles_description


def test_extract_job_criteria_wraps_api_error(monkeypatch):
    client = Mock()
    client.messages.create.side_effect = anthropic.APIError(message="boom", request=Mock(), body=None)
    monkeypatch.setattr("cv_extraction.anthropic.Anthropic", lambda api_key: client)

    with pytest.raises(CVExtractionError, match="Claude API error"):
        extract_job_criteria("cv text", "fake-key")
