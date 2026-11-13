"""Turn CV text into structured job search criteria using Claude."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import anthropic

MODEL = "claude-haiku-4-5-20251001"
MAX_TITLES = 15  # each title = one full paginated Adzuna call; cap keeps free-tier calls in check

def _build_tool(max_titles: int) -> dict:
    return {
        "name": "extract_search_criteria",
        "description": (
            "Extract job search titles, a candidate's likely job-search location and country, "
            "and a reasonable minimum salary floor from a CV."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "titles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        f"Up to {max_titles} distinct job titles or search-engine queries this candidate "
                        "should search for, most relevant first. Use as many as are genuinely distinct "
                        "and relevant — don't pad with near-duplicates just to hit the limit."
                    ),
                },
                "suggested_location": {
                    "type": "string",
                    "description": "Candidate's likely job search location, e.g. 'Seattle, WA'. Omit if not determinable.",
                },
                "suggested_country": {
                    "type": "string",
                    "description": (
                        "Lowercase two-letter Adzuna country code matching suggested_location's country, "
                        "e.g. 'us', 'gb', 'au', 'ca', 'de'. Omit if not determinable."
                    ),
                },
                "suggested_salary_min": {
                    "type": "integer",
                    "description": (
                        "A reasonable minimum annual salary floor, in the local currency implied by the "
                        "candidate's location (do not convert to USD), given the candidate's experience level. "
                        "Omit if not determinable."
                    ),
                },
            },
            "required": ["titles"],
        },
    }


@dataclass
class JobCriteria:
    titles: list[str]
    suggested_location: Optional[str]
    suggested_country: Optional[str]
    suggested_salary_min: Optional[int]


class CVExtractionError(RuntimeError):
    pass


def extract_job_criteria(
    cv_text: str,
    api_key: str,
    max_titles: int = MAX_TITLES,
    notes: Optional[str] = None,
) -> JobCriteria:
    prompt = f"Extract job search criteria from this CV:\n\n{cv_text}"
    if notes:
        prompt += (
            "\n\nAdditional guidance from the candidate — use this to broaden or adjust which "
            f"titles you choose, not just what's literally in the CV:\n{notes}"
        )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=[_build_tool(max_titles)],
            tool_choice={"type": "tool", "name": "extract_search_criteria"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise CVExtractionError(f"Claude API error: {exc}") from exc

    tool_use = next(block for block in response.content if block.type == "tool_use")
    data = tool_use.input
    titles = data.get("titles") or []
    if not titles:
        raise CVExtractionError("Claude did not return any job titles from the CV")

    return JobCriteria(
        titles=titles[:max_titles],
        suggested_location=data.get("suggested_location"),
        suggested_country=data.get("suggested_country"),
        suggested_salary_min=data.get("suggested_salary_min"),
    )
