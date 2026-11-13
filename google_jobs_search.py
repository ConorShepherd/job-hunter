"""
Search Google Jobs (via SerpApi) by title, location, and radius.

SerpApi aggregates Google Jobs, which itself pulls from many underlying boards
(Indeed, LinkedIn, ZipRecruiter, company sites, etc.) in one query — broad
coverage, but the SerpApi quota is far more limited than Adzuna's free
tier (each page of results is a billed "search"), so this is used sparingly
elsewhere in the app (see GOOGLE_JOBS_MAX_TITLES in find_jobs.py).

Setup:
    1. Get a key at https://serpapi.com (paid plans; small free tier)
    2. Add SERPAPI_API_KEY to your .env file

Usage:
    python google_jobs_search.py --title "data engineer" --location London --distance 25
"""
from __future__ import annotations

import argparse
import functools
import os
import sys
from dataclasses import asdict
from typing import Optional
import json

import requests
from dotenv import load_dotenv

from adzuna_search import JobListing, print_table

API_BASE = "https://serpapi.com/search"
LOCATIONS_API = "https://serpapi.com/locations.json"  # free, no api_key/credits needed
RESULTS_PER_PAGE = 10  # fixed by SerpApi's google_jobs engine
MAX_PAGES = 10  # safety bound on top of max_results


class GoogleJobsError(RuntimeError):
    pass


def _miles_to_km(miles: int) -> int:
    return round(miles * 1.60934)


@functools.lru_cache(maxsize=64)
def _resolve_location(location: str) -> Optional[str]:
    """Resolve free text to a SerpApi canonical location name.

    The google_jobs engine rejects location strings that don't exactly match
    one of Google's known locations (e.g. "Cheltenham, Gloucestershire" 400s,
    but the bare city "Cheltenham" resolves to "Cheltenham,England,United
    Kingdom") — CV-derived location text is rarely already in that exact
    canonical form, so this looks it up rather than passing it through as-is.
    Falls back to just the first comma-separated segment (usually the city
    name alone), then gives up and returns None if nothing matches.
    """
    candidates = [location]
    if "," in location:
        candidates.append(location.split(",")[0].strip())

    for candidate in candidates:
        try:
            response = requests.get(LOCATIONS_API, params={"q": candidate, "limit": 1}, timeout=10)
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError):
            continue
        if results:
            return results[0].get("canonical_name")

    return None


def search_jobs(
    api_key: str,
    title: str,
    salary_min: Optional[int] = None,
    location: Optional[str] = None,
    distance: Optional[int] = None,
    country: Optional[str] = None,
    max_results: int = 100,
) -> list[JobListing]:
    """Query SerpApi's Google Jobs engine and return structured job listings.

    salary_min is not applied server-side (Google Jobs doesn't expose a reliable
    structured salary field to filter on) — results are returned unfiltered by
    salary; callers that need a floor should filter listings.salary_min themselves.
    """
    listings: list[JobListing] = []
    next_page_token = None
    resolved_location = _resolve_location(location) if location else None

    for _ in range(MAX_PAGES):
        if len(listings) >= max_results:
            break

        params = {"engine": "google_jobs", "api_key": api_key, "q": title, "hl": "en"}
        if resolved_location:
            params["location"] = resolved_location
        if distance is not None:
            params["lrad"] = _miles_to_km(distance)
        if country:
            params["gl"] = country
        if next_page_token:
            params["next_page_token"] = next_page_token

        response = requests.get(API_BASE, params=params, timeout=60)

        if response.status_code == 401:
            raise GoogleJobsError("SerpApi rejected the request (401). Check SERPAPI_API_KEY.")
        if not response.ok:
            raise GoogleJobsError(f"SerpApi error {response.status_code}: {response.text[:300]}")

        data = response.json()
        if data.get("error"):
            raise GoogleJobsError(f"SerpApi error: {data['error']}")

        results = data.get("jobs_results", [])
        if not results:
            break

        for job in results:
            apply_options = job.get("apply_options") or []
            url = apply_options[0]["link"] if apply_options else job.get("share_link", "")
            listings.append(
                JobListing(
                    title=(job.get("title") or "").strip(),
                    company=job.get("company_name") or "Unknown",
                    location=job.get("location") or "Unknown",
                    salary_min=None,
                    salary_max=None,
                    created=(job.get("detected_extensions") or {}).get("posted_at", ""),
                    url=url,
                    description=(job.get("description") or "").strip(),
                    id=job.get("job_id", ""),
                    source="google_jobs",
                )
            )
            if len(listings) >= max_results:
                break

        next_page_token = (data.get("serpapi_pagination") or {}).get("next_page_token")
        if not next_page_token:
            break

    return listings


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Search Google Jobs via SerpApi.")
    parser.add_argument("--title", required=True, help="Job title / keywords to search for")
    parser.add_argument("--location", default=None, help="Location, e.g. 'London'")
    parser.add_argument("--distance", type=int, default=None, help="Search radius in miles around --location")
    parser.add_argument("--country", default=None, help="Two-letter country code, e.g. 'gb', 'us'")
    parser.add_argument("--max-results", type=int, default=100, help="Max results to return")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a table")
    parser.add_argument("--html", action="store_true", help="Write a sortable/filterable HTML report instead of printing")
    parser.add_argument("--html-output", default="results.html", help="Path for --html output (default: results.html)")
    args = parser.parse_args()

    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        print(
            "Missing SERPAPI_API_KEY. Set it in a .env file (see .env.example) or as an environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        listings = search_jobs(
            api_key=api_key,
            title=args.title,
            location=args.location,
            distance=args.distance,
            country=args.country,
            max_results=args.max_results,
        )
    except GoogleJobsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.html:
        from html_report import write_report

        write_report([asdict(job) for job in listings], path=args.html_output, title=f"Google Jobs: {args.title}")
        print(f"Wrote {len(listings)} results to {args.html_output}")
    elif args.json:
        print(json.dumps([asdict(job) for job in listings], indent=2))
    else:
        print_table(listings)


if __name__ == "__main__":
    main()
