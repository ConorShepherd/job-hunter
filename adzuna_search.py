"""
Search Adzuna job listings by title, minimum salary, and location.

Setup:
    1. Get a free API key at https://developer.adzuna.com/
    2. Copy .env.example to .env and fill in ADZUNA_APP_ID / ADZUNA_APP_KEY
    3. pip install -r requirements.txt

Usage:
    python adzuna_search.py --title "data engineer" --salary-min 120000 --location "Seattle, WA"
    python adzuna_search.py --title "backend engineer" --salary-min 130000 --location Austin --json
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, asdict
from typing import Optional
import json

import requests
from dotenv import load_dotenv

API_BASE = "https://api.adzuna.com/v1/api/jobs"


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    salary_min: Optional[float]
    salary_max: Optional[float]
    created: str
    url: str
    description: str
    id: str
    source: str


class AdzunaError(RuntimeError):
    pass


def search_jobs(
    app_id: str,
    app_key: str,
    title: str,
    salary_min: Optional[int] = None,
    location: Optional[str] = None,
    distance: Optional[int] = None,
    country: str = "us",
    max_results: int = 20,
    results_per_page: int = 20,
) -> list[JobListing]:
    """Query the Adzuna search endpoint and return structured job listings.

    `distance` is a radius in miles around `location` ("as the crow flies", not
    commute time) — Adzuna's own default is narrow (exact-area matching), so pass
    this explicitly to catch commutable-but-not-local areas.
    """
    listings: list[JobListing] = []
    page = 1

    while len(listings) < max_results:
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": title,
            "results_per_page": min(results_per_page, max_results - len(listings)),
            "content-type": "application/json",
        }
        if salary_min is not None:
            params["salary_min"] = salary_min
        if location:
            params["where"] = location
        if distance is not None:
            params["distance"] = distance

        url = f"{API_BASE}/{country}/search/{page}"
        response = requests.get(url, params=params, timeout=60)

        if response.status_code == 401:
            raise AdzunaError(
                "Adzuna rejected the request (401). Check ADZUNA_APP_ID / ADZUNA_APP_KEY."
            )
        if not response.ok:
            raise AdzunaError(
                f"Adzuna API error {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        results = data.get("results", [])
        if not results:
            break

        for job in results:
            listings.append(
                JobListing(
                    title=job.get("title", "").strip(),
                    company=(job.get("company") or {}).get("display_name", "Unknown"),
                    location=(job.get("location") or {}).get("display_name", "Unknown"),
                    salary_min=job.get("salary_min"),
                    salary_max=job.get("salary_max"),
                    created=job.get("created", ""),
                    url=job.get("redirect_url", ""),
                    description=(job.get("description") or "").strip(),
                    id=job.get("id", ""),
                    source="adzuna",
                )
            )
            if len(listings) >= max_results:
                break

        page += 1
        if page > data.get("count", 0) // results_per_page + 1:
            break

    return listings


def print_table(listings: list[JobListing]) -> None:
    if not listings:
        print("No results found.")
        return
    for job in listings:
        salary = ""
        if job.salary_min or job.salary_max:
            lo = f"${job.salary_min:,.0f}" if job.salary_min else "?"
            hi = f"${job.salary_max:,.0f}" if job.salary_max else "?"
            salary = f" [{lo} - {hi}]"
        print(f"{job.title} @ {job.company}{salary}")
        print(f"  {job.location} | posted {job.created[:10]}")
        print(f"  {job.url}")
        print()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Search Adzuna job listings.")
    parser.add_argument("--title", required=True, help="Job title / keywords to search for")
    parser.add_argument("--salary-min", type=int, default=None, help="Minimum salary floor")
    parser.add_argument("--location", default=None, help="Location, e.g. 'Seattle, WA'")
    parser.add_argument("--distance", type=int, default=None, help="Search radius in miles around --location")
    parser.add_argument("--country", default="us", help="Adzuna country code (default: us)")
    parser.add_argument("--max-results", type=int, default=20, help="Max results to return")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of a table")
    parser.add_argument("--html", action="store_true", help="Write a sortable/filterable HTML report instead of printing")
    parser.add_argument("--html-output", default="results.html", help="Path for --html output (default: results.html)")
    args = parser.parse_args()

    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print(
            "Missing ADZUNA_APP_ID / ADZUNA_APP_KEY. Set them in a .env file "
            "(see .env.example) or as environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        listings = search_jobs(
            app_id=app_id,
            app_key=app_key,
            title=args.title,
            salary_min=args.salary_min,
            location=args.location,
            distance=args.distance,
            country=args.country,
            max_results=args.max_results,
        )
    except AdzunaError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.html:
        from html_report import write_report

        write_report([asdict(job) for job in listings], path=args.html_output, title=f"Adzuna: {args.title}")
        print(f"Wrote {len(listings)} results to {args.html_output}")
    elif args.json:
        print(json.dumps([asdict(job) for job in listings], indent=2))
    else:
        print_table(listings)


if __name__ == "__main__":
    main()
