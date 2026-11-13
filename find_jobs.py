"""
Upload a CV, get relevant jobs back.

Turns a CV PDF into a set of candidate job titles (plus a suggested location,
country, and salary floor) via Claude, runs each title through every enabled
job source, and returns one merged, deduped list of listings — optionally
ranked by fit. A saved profile.json (see setup_profile.py) supplies commute
radius, salary floor, and excluded companies without re-typing them each run.

Usage:
    python find_jobs.py --cv resume.pdf
    python find_jobs.py --cv resume.pdf --location "Austin, TX" --salary-min 150000 --json
    python find_jobs.py --cv resume.pdf --score
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import Optional, Protocol

from dotenv import load_dotenv

import cache
from adzuna_search import AdzunaError, JobListing, print_table, search_jobs
from cv_extraction import CVExtractionError, extract_job_criteria
from cv_parser import CVParseError, extract_text
from google_jobs_search import GoogleJobsError
from google_jobs_search import search_jobs as google_jobs_search_jobs
from job_scoring import JobScoringError, ScoredJob, score_jobs
from profile import Profile, load_profile

DEFAULT_DISTANCE_MILES = 25  # Adzuna defaults to tight, near-exact matching otherwise
GOOGLE_JOBS_MAX_TITLES = 50  # safety ceiling only — well above cv_extraction.MAX_TITLES (15), so it
# doesn't restrict a normal run; raise cv_extraction.MAX_TITLES freely without needing to touch this too


class JobSource(Protocol):
    def search(
        self,
        title: str,
        salary_min: Optional[int],
        location: Optional[str],
        max_results: int,
        distance: Optional[int] = None,
    ) -> list[JobListing]:
        ...


class AdzunaSource:
    def __init__(self, app_id: str, app_key: str, country: str):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country

    def search(self, title, salary_min, location, max_results, distance=None):
        return search_jobs(
            self.app_id,
            self.app_key,
            title,
            salary_min=salary_min,
            location=location,
            distance=distance,
            country=self.country,
            max_results=max_results,
        )


class GoogleJobsSource:
    def __init__(self, api_key: str, country: Optional[str] = None):
        self.api_key = api_key
        self.country = country

    def search(self, title, salary_min, location, max_results, distance=None):
        listings = google_jobs_search_jobs(
            self.api_key,
            title,
            location=location,
            distance=distance,
            country=self.country,
            max_results=max_results,
        )
        if salary_min is None:
            return listings
        # Google Jobs has no reliable structured salary to filter on server-side;
        # apply the floor client-side, keeping listings with no salary data at all.
        return [j for j in listings if j.salary_min is None or j.salary_min >= salary_min]


def titles_for_source(source: JobSource, titles: list[str]) -> list[str]:
    if isinstance(source, GoogleJobsSource):
        return titles[:GOOGLE_JOBS_MAX_TITLES]
    return titles


def dedupe(listings: list[JobListing]) -> list[JobListing]:
    seen = set()
    result = []
    for job in listings:
        key = (job.source, job.id)
        if key in seen:
            continue
        seen.add(key)
        result.append(job)
    return result


def filter_excluded_companies(listings: list[JobListing], excluded_companies: list[str]) -> list[JobListing]:
    if not excluded_companies:
        return listings
    excluded_lower = [c.lower() for c in excluded_companies]
    return [job for job in listings if not any(ec in job.company.lower() for ec in excluded_lower)]


def resolve_location(cli_location: Optional[str], suggested_location: Optional[str]) -> Optional[str]:
    return cli_location or suggested_location


def resolve_salary_min(
    cli_salary_min: Optional[int],
    profile_salary_min: Optional[int],
    suggested_salary_min: Optional[int],
) -> Optional[int]:
    if cli_salary_min is not None:
        return cli_salary_min
    if profile_salary_min is not None:
        return profile_salary_min
    return suggested_salary_min


def resolve_country(cli_country: Optional[str], suggested_country: Optional[str]) -> str:
    return cli_country or suggested_country or "us"


def resolve_distance(cli_distance: Optional[int], profile_max_commute_miles: Optional[int]) -> int:
    if cli_distance is not None:
        return cli_distance
    if profile_max_commute_miles is not None:
        return profile_max_commute_miles
    return DEFAULT_DISTANCE_MILES


def print_scored_table(scored: list[ScoredJob]) -> None:
    if not scored:
        print("No results found.")
        return
    for sj in scored:
        job = sj.job
        salary = ""
        if job.salary_min or job.salary_max:
            lo = f"${job.salary_min:,.0f}" if job.salary_min else "?"
            hi = f"${job.salary_max:,.0f}" if job.salary_max else "?"
            salary = f" [{lo} - {hi}]"
        print(f"[{sj.score}] {job.title} @ {job.company}{salary}")
        print(f"  {job.location} | posted {job.created[:10]}")
        print(f"  {sj.rationale}")
        print(f"  {job.url}")
        print()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Find jobs matching your CV.")
    parser.add_argument("--cv", required=True, help="Path to your CV (PDF)")
    parser.add_argument("--location", default=None, help="Override the CV-suggested location")
    parser.add_argument("--salary-min", type=int, default=None, help="Override the CV-suggested/profile salary floor")
    parser.add_argument("--country", default=None, help="Override the CV-suggested Adzuna country code (falls back to 'us')")
    parser.add_argument("--distance", type=int, default=None, help="Override the profile/default search radius in miles")
    parser.add_argument("--max-results-per-title", type=int, default=10, help="Max results per searched title, per source")
    parser.add_argument("--score", action="store_true", help="Rank results by fit against the CV using Claude")
    parser.add_argument("--no-cache", action="store_true", help="Bypass the CV-criteria and job-score caches")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a table")
    parser.add_argument("--html", action="store_true", help="Write a sortable/filterable HTML report instead of printing")
    parser.add_argument("--html-output", default="results.html", help="Path for --html output (default: results.html)")
    args = parser.parse_args()

    adzuna_app_id = os.environ.get("ADZUNA_APP_ID")
    adzuna_app_key = os.environ.get("ADZUNA_APP_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    serpapi_key = os.environ.get("SERPAPI_API_KEY")
    if not adzuna_app_id or not adzuna_app_key or not anthropic_key:
        print(
            "Missing ADZUNA_APP_ID / ADZUNA_APP_KEY / ANTHROPIC_API_KEY. "
            "Set them in a .env file (see .env.example) or as environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)

    profile = load_profile()
    if profile is None:
        print("No profile.json found — run setup_profile.py to save commute/salary/exclusion preferences.", file=sys.stderr)

    try:
        cv_text = extract_text(args.cv)
    except CVParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    profile_notes = profile.notes if profile else None
    cv_hash = cache.cv_text_hash(cv_text, profile_notes)
    criteria = None if args.no_cache else cache.load_cached_criteria(cv_hash)
    if criteria is not None:
        print("Using cached CV criteria (pass --no-cache to force re-extraction).", file=sys.stderr)
    else:
        try:
            criteria = extract_job_criteria(cv_text, anthropic_key, notes=profile_notes)
        except CVExtractionError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        if not args.no_cache:
            cache.save_cached_criteria(cv_hash, criteria)

    location = resolve_location(args.location, criteria.suggested_location)
    salary_min = resolve_salary_min(
        args.salary_min, profile.salary_min_override if profile else None, criteria.suggested_salary_min
    )
    country = resolve_country(args.country, criteria.suggested_country)
    distance = resolve_distance(args.distance, profile.max_commute_miles if profile else None)

    print(f"Extracted titles: {criteria.titles}", file=sys.stderr)
    print(
        f"Using location: {location!r}, salary_min: {salary_min!r}, country: {country!r}, distance: {distance} miles",
        file=sys.stderr,
    )

    sources: list[JobSource] = [AdzunaSource(adzuna_app_id, adzuna_app_key, country)]
    if serpapi_key:
        sources.append(GoogleJobsSource(serpapi_key, country))
        if len(criteria.titles) > GOOGLE_JOBS_MAX_TITLES:
            print(f"Google Jobs source enabled (capped to top {GOOGLE_JOBS_MAX_TITLES} titles).", file=sys.stderr)
        else:
            print("Google Jobs source enabled.", file=sys.stderr)

    all_listings: list[JobListing] = []
    attempts = 0
    failures = 0
    for source in sources:
        for title in titles_for_source(source, criteria.titles):
            attempts += 1
            print(f"Searching {type(source).__name__} for '{title}'...", file=sys.stderr)
            try:
                all_listings.extend(source.search(title, salary_min, location, args.max_results_per_title, distance=distance))
            except (AdzunaError, GoogleJobsError) as exc:
                print(f"Warning: search for '{title}' failed: {exc}", file=sys.stderr)
                failures += 1

    if failures == attempts:
        print("Error: every search failed.", file=sys.stderr)
        sys.exit(1)

    listings = dedupe(all_listings)
    if profile:
        listings = filter_excluded_companies(listings, profile.excluded_companies)

    if not listings:
        print("No results found.", file=sys.stderr)
        return

    if args.score:
        score_cache = {} if args.no_cache else cache.load_score_cache(cv_hash)
        cached_scored = []
        to_score = []
        for job in listings:
            key = f"{job.source}:{job.id}"
            if key in score_cache:
                entry = score_cache[key]
                cached_scored.append(ScoredJob(job=job, score=entry["score"], rationale=entry["rationale"]))
            else:
                to_score.append(job)
        print(f"{len(cached_scored)} jobs already scored (cached), {len(to_score)} new to score.", file=sys.stderr)

        newly_scored = []
        if to_score:
            try:
                newly_scored = score_jobs(cv_text, to_score, anthropic_key, profile=profile)
            except JobScoringError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
            for sj in newly_scored:
                score_cache[f"{sj.job.source}:{sj.job.id}"] = {"score": sj.score, "rationale": sj.rationale}
            if not args.no_cache:
                cache.save_score_cache(cv_hash, score_cache)

        scored = sorted(cached_scored + newly_scored, key=lambda sj: sj.score, reverse=True)
        rows = [{**asdict(sj.job), "score": sj.score, "rationale": sj.rationale} for sj in scored]

        if args.html:
            from html_report import write_report

            write_report(rows, path=args.html_output, title="Job Matches")
            print(f"Wrote {len(rows)} results to {args.html_output}", file=sys.stderr)
        elif args.json:
            print(json.dumps(rows, indent=2))
        else:
            print_scored_table(scored)
        return

    if args.html:
        from html_report import write_report

        write_report([asdict(job) for job in listings], path=args.html_output, title="Job Matches")
        print(f"Wrote {len(listings)} results to {args.html_output}", file=sys.stderr)
    elif args.json:
        print(json.dumps([asdict(job) for job in listings], indent=2))
    else:
        print_table(listings)


if __name__ == "__main__":
    main()
