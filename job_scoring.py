"""Score job listings against a CV using Claude, for ranking by fit."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import anthropic

from adzuna_search import JobListing
from profile import Profile

MODEL = "claude-haiku-4-5-20251001"
MAX_JOBS_TO_SCORE = 40  # batch size per Claude call — large result sets are split into multiple batches, not truncated

TOOL = {
    "name": "score_jobs",
    "description": "Score each job listing's fit for a candidate given their CV, 0-100, with a one-sentence rationale.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The job listing's 'index' field, copied exactly from the input."},
                        "score": {"type": "integer", "description": "Fit score from 0 (poor fit) to 100 (excellent fit)."},
                        "rationale": {"type": "string", "description": "One sentence explaining the score."},
                    },
                    "required": ["index", "score", "rationale"],
                },
            },
        },
        "required": ["scores"],
    },
}


@dataclass
class ScoredJob:
    job: JobListing
    score: int
    rationale: str


class JobScoringError(RuntimeError):
    pass


def _preferences_block(profile: Optional[Profile]) -> str:
    if profile is None:
        return ""
    lines = []
    if profile.max_commute_miles is not None:
        lines.append(f"Maximum acceptable commute: {profile.max_commute_miles} miles")
    lines.append(f"Remote roles acceptable: {'yes' if profile.remote_ok else 'no'}")
    lines.append(f"Willing to relocate: {'yes' if profile.willing_to_relocate else 'no'}")
    if profile.notes:
        lines.append(f"Additional notes: {profile.notes}")
    return "\n\nCandidate preferences (weigh these alongside CV fit):\n" + "\n".join(f"- {l}" for l in lines)


def score_jobs(
    cv_text: str,
    listings: list[JobListing],
    api_key: str,
    profile: Optional[Profile] = None,
) -> list[ScoredJob]:
    if not listings:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    scored: list[ScoredJob] = []
    for i in range(0, len(listings), MAX_JOBS_TO_SCORE):
        batch = listings[i : i + MAX_JOBS_TO_SCORE]
        scored.extend(_score_batch(client, cv_text, batch, profile))

    scored.sort(key=lambda sj: sj.score, reverse=True)
    return scored


def _score_batch(
    client: anthropic.Anthropic,
    cv_text: str,
    listings: list[JobListing],
    profile: Optional[Profile],
) -> list[ScoredJob]:
    job_summaries = [
        {
            "index": i,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "description": job.description[:500],
        }
        for i, job in enumerate(listings)
    ]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "score_jobs"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Here is a candidate's CV, followed by a list of job listings. "
                        "Score each listing's fit for this candidate."
                        f"{_preferences_block(profile)}\n\n"
                        f"CV:\n{cv_text}\n\nJob listings:\n{job_summaries}"
                    ),
                }
            ],
        )
    except anthropic.APIError as exc:
        raise JobScoringError(f"Claude API error: {exc}") from exc

    tool_use = next(block for block in response.content if block.type == "tool_use")
    scores_by_index = {s["index"]: s for s in tool_use.input.get("scores", [])}

    return [
        ScoredJob(job=job, score=scores_by_index[i]["score"], rationale=scores_by_index[i]["rationale"])
        for i, job in enumerate(listings)
        if i in scores_by_index
    ]
