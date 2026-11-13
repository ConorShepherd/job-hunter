"""MCP server exposing Adzuna job search and CV-driven job discovery as tools."""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import cache
from adzuna_search import AdzunaError, search_jobs
from cv_extraction import CVExtractionError, extract_job_criteria
from cv_parser import CVParseError, extract_text
from find_jobs import (
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
from google_jobs_search import GoogleJobsError
from job_scoring import JobScoringError, ScoredJob, score_jobs
from profile import load_profile

load_dotenv()

mcp = FastMCP("job-hunter")


def _credentials() -> tuple[str, str, str]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not app_id or not app_key or not anthropic_key:
        raise RuntimeError(
            "Missing ADZUNA_APP_ID / ADZUNA_APP_KEY / ANTHROPIC_API_KEY in the environment (.env)."
        )
    return app_id, app_key, anthropic_key


@mcp.tool()
def search_adzuna_jobs(
    title: str,
    salary_min: Optional[int] = None,
    location: Optional[str] = None,
    distance: Optional[int] = None,
    country: str = "us",
    max_results: int = 20,
) -> list[dict]:
    """Search Adzuna for jobs matching a title, with an optional salary floor, location, and search radius in miles."""
    app_id, app_key, _ = _credentials()
    try:
        listings = search_jobs(
            app_id, app_key, title,
            salary_min=salary_min, location=location, distance=distance,
            country=country, max_results=max_results,
        )
    except AdzunaError as exc:
        raise RuntimeError(str(exc)) from exc
    return [asdict(job) for job in listings]


@mcp.tool()
def find_jobs_from_cv(
    cv_path: str,
    location: Optional[str] = None,
    salary_min: Optional[int] = None,
    country: Optional[str] = None,
    distance: Optional[int] = None,
    max_results_per_title: int = 10,
    score: bool = True,
    use_cache: bool = True,
    html_output: Optional[str] = None,
) -> list[dict]:
    """
    Parse a CV PDF, have Claude infer search titles/location/country/salary floor,
    search every enabled job source (Adzuna; Google Jobs via SerpApi if
    SERPAPI_API_KEY is set, capped to the top few titles to protect its more
    limited quota) for each title, dedupe the results, apply any saved
    profile.json (commute radius, salary floor, excluded companies), and
    (by default) rank them by fit against the CV. Explicit location/salary_min/
    country/distance override the CV-derived and profile-derived suggestions.
    Repeat calls with the same CV and job reuse cached extraction/scoring instead
    of re-calling Claude. If html_output is set, also writes a sortable/
    filterable HTML report to that path (the returned list is unaffected).
    """
    app_id, app_key, anthropic_key = _credentials()
    serpapi_key = os.environ.get("SERPAPI_API_KEY")
    profile = load_profile()

    try:
        cv_text = extract_text(cv_path)
    except CVParseError as exc:
        raise RuntimeError(str(exc)) from exc

    profile_notes = profile.notes if profile else None
    cv_hash = cache.cv_text_hash(cv_text, profile_notes)
    criteria = cache.load_cached_criteria(cv_hash) if use_cache else None
    if criteria is None:
        try:
            criteria = extract_job_criteria(cv_text, anthropic_key, notes=profile_notes)
        except CVExtractionError as exc:
            raise RuntimeError(str(exc)) from exc
        if use_cache:
            cache.save_cached_criteria(cv_hash, criteria)

    resolved_location = resolve_location(location, criteria.suggested_location)
    resolved_salary_min = resolve_salary_min(
        salary_min, profile.salary_min_override if profile else None, criteria.suggested_salary_min
    )
    resolved_country = resolve_country(country, criteria.suggested_country)
    resolved_distance = resolve_distance(distance, profile.max_commute_miles if profile else None)

    sources = [AdzunaSource(app_id, app_key, resolved_country)]
    if serpapi_key:
        sources.append(GoogleJobsSource(serpapi_key, resolved_country))

    all_listings = []
    for source in sources:
        for search_title in titles_for_source(source, criteria.titles):
            try:
                all_listings.extend(
                    source.search(
                        search_title, resolved_salary_min, resolved_location,
                        max_results_per_title, distance=resolved_distance,
                    )
                )
            except (AdzunaError, GoogleJobsError):
                continue

    listings = dedupe(all_listings)
    if profile:
        listings = filter_excluded_companies(listings, profile.excluded_companies)

    if not score or not listings:
        rows = [asdict(job) for job in listings]
        if html_output:
            from html_report import write_report

            write_report(rows, path=html_output, title="Job Matches")
        return rows

    score_cache = cache.load_score_cache(cv_hash) if use_cache else {}
    cached_scored, to_score = [], []
    for job in listings:
        key = f"{job.source}:{job.id}"
        if key in score_cache:
            entry = score_cache[key]
            cached_scored.append(ScoredJob(job=job, score=entry["score"], rationale=entry["rationale"]))
        else:
            to_score.append(job)

    newly_scored = []
    if to_score:
        try:
            newly_scored = score_jobs(cv_text, to_score, anthropic_key, profile=profile)
        except JobScoringError as exc:
            raise RuntimeError(str(exc)) from exc
        for sj in newly_scored:
            score_cache[f"{sj.job.source}:{sj.job.id}"] = {"score": sj.score, "rationale": sj.rationale}
        if use_cache:
            cache.save_score_cache(cv_hash, score_cache)

    scored = sorted(cached_scored + newly_scored, key=lambda sj: sj.score, reverse=True)
    rows = [{**asdict(sj.job), "score": sj.score, "rationale": sj.rationale} for sj in scored]
    if html_output:
        from html_report import write_report

        write_report(rows, path=html_output, title="Job Matches")
    return rows


if __name__ == "__main__":
    mcp.run()
