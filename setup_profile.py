"""
One-time interactive setup for your candidate profile.

Run this once; find_jobs.py and the MCP server pick up profile.json
automatically from then on. Re-run any time to update your preferences.

Usage:
    python setup_profile.py
"""
from __future__ import annotations

from profile import Profile, save_profile


def ask_int(prompt: str) -> "int | None":
    answer = input(prompt).strip()
    return int(answer) if answer else None


def ask_yes_no(prompt: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer.startswith("y")


def main() -> None:
    print("Setting up your job search profile. Press enter to skip any question.\n")

    max_commute_miles = ask_int("Max commute distance in miles (blank = no limit): ")
    remote_ok = ask_yes_no("Are remote roles OK?", default=True)
    willing_to_relocate = ask_yes_no("Willing to relocate for the right role?", default=False)
    salary_min_override = ask_int("Salary floor override, if any (blank = let the CV decide): ")

    excluded_raw = input("Companies to exclude, comma-separated (blank = none): ").strip()
    excluded_companies = [c.strip() for c in excluded_raw.split(",") if c.strip()]

    notes = input("Anything else worth knowing (blank = nothing)? ").strip() or None

    profile = Profile(
        max_commute_miles=max_commute_miles,
        remote_ok=remote_ok,
        willing_to_relocate=willing_to_relocate,
        salary_min_override=salary_min_override,
        excluded_companies=excluded_companies,
        notes=notes,
    )
    save_profile(profile)
    print("\nSaved to profile.json.")


if __name__ == "__main__":
    main()
