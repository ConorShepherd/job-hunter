# Architecture

How this app is built, what each piece does, what it costs, and the reasoning behind a few design decisions — captured here rather than in code comments since none of it is obvious from reading the files alone.

See [SCHEDULED_MODE.md](SCHEDULED_MODE.md) for a sketch of a future unattended/scheduled mode using the Batches API (not implemented).

## Flow

```
CV.pdf
  │
  ▼
cv_parser.extract_text()                 PDF → text. No API cost.
  │
  ▼
cache: cv_hash = sha256(cv_text)
  │  hit? ──────────────────────────────► reuse cached JobCriteria, skip below
  │  miss
  ▼
cv_extraction.extract_job_criteria()     Claude call #1 (Haiku). CV text → titles[],
  │                                       suggested_location, suggested_country,
  │                                       suggested_salary_min. Cached by cv_hash.
  ▼
find_jobs.py orchestrator
  │  resolve location/salary/country/distance: CLI flag > profile.json > CV suggestion > default
  │  for each enabled source (Adzuna always; Google Jobs if SERPAPI_API_KEY set,
  │  capped to the top GOOGLE_JOBS_MAX_TITLES titles):
  │    for each title: source.search(title, salary_min, location, max_results, distance)
  │  dedupe() by (source, id)
  │  filter_excluded_companies() from profile.json
  ▼
job_scoring.score_jobs()                 Claude call #2 (Haiku), only if --score.
  │                                       Split into cached scores (by cv_hash + source:id)
  │                                       and new listings; only new ones hit the API.
  ▼
table / JSON output
```

`mcp_server.py` wraps the same orchestration logic as two MCP tools (`search_adzuna_jobs`, `find_jobs_from_cv`) rather than reimplementing it — it imports and calls the same functions `find_jobs.py`'s CLI does.

## Components

| File | Responsibility | Touches Claude? |
|---|---|---|
| `adzuna_search.py` | Adzuna API client + standalone CLI + shared `JobListing` dataclass + shared `print_table()` | No |
| `google_jobs_search.py` | Google Jobs client via SerpApi + standalone CLI, same `JobListing` shape | No |
| `cv_parser.py` | PDF → plain text | No |
| `cv_extraction.py` | CV text → `JobCriteria` (titles, location, country, salary floor) via a forced tool call | Yes — call #1 |
| `job_scoring.py` | Job listings + CV (+ optional profile) → `ScoredJob` list via a forced tool call | Yes — call #2 |
| `profile.py` | `Profile` dataclass + JSON load/save | No |
| `setup_profile.py` | One-time interactive Q&A that writes `profile.json` | No |
| `cache.py` | Hash-keyed disk cache for CV criteria and job scores | No |
| `html_report.py` | Renders listings (scored or not) into one self-contained, sortable/filterable HTML file | No |
| `find_jobs.py` | Orchestrates everything above: resolves precedence, runs multi-source search, dedupes, caches, scores, prints | Calls into the above |
| `mcp_server.py` | Exposes the same orchestration as two MCP tools | Calls into the above |

## What costs Claude credits

Only two call sites, both on **Haiku 4.5** (`claude-haiku-4-5-20251001`, $1.00 / $5.00 per million input/output tokens):

- **CV extraction** (`cv_extraction.py`): ~1–3K input tokens (CV text + tool schema) → a few hundred output tokens. Roughly **$0.002–0.004 per call**, once per CV+notes combination (cached after that).
- **Job scoring** (`job_scoring.py`): batches of up to `MAX_JOBS_TO_SCORE` (40) job summaries per Claude call — CV text repeated in every batch's prompt (~1–3K tokens) plus ~150 tokens/job, one score+rationale per job as output. Roughly **$0.01–0.02 per batch of 40**. A run with, say, 120 new (uncached) jobs makes 3 batched calls, not 1 — cost scales with the number of *new* jobs, not a flat per-run amount.

A typical `--score` run (a few dozen new jobs) costs a couple of cents in Claude usage — Adzuna and Google Jobs calls don't touch Claude's cost at all (separate quotas; Google Jobs' SerpApi quota is its own real constraint, see [Job sources](#job-sources)). The caching described below is what keeps the Claude side cheap over repeated runs: without it, every job seen again tomorrow would burn another share of a batch.

**Gotcha (fixed):** `score_jobs()` originally did `listings = listings[:MAX_JOBS_TO_SCORE]` — a hard truncation, not a cap on cost. With more than 40 new jobs in a single run, everything past the 40th was silently dropped: never scored, never cached, never shown in output or the HTML report, with no warning printed. `find_jobs.py --score` would report e.g. "120 new to score" and then the report would show only 40 rows. Fixed by splitting `listings` into `MAX_JOBS_TO_SCORE`-sized batches and making one Claude call per batch, combining and re-sorting the results — every job now gets scored, just across more calls (and therefore proportionally more cost) when there are more than 40 new ones. If you see `already scored (cached)` + `new to score` not adding up to the row count in the final output, that's the earlier bug — this fix is what closes that gap; a very occasional single job missing is expected (the model can omit a score for one item) and not a batching issue.

**Gotcha (fixed):** the scoring tool schema originally asked Claude to echo back each job's `"source:id"` string verbatim as the correlation key for matching scores to jobs. That's fine for Adzuna's short numeric IDs, but Google Jobs' `job_id` is a base64-encoded blob averaging ~370 characters (up to 760 seen in testing). In a batch of 40 jobs with several Google Jobs entries mixed in, reproducing those IDs alone could consume most of `max_tokens` (4096) before any scores were written, silently truncating the response — a run reporting "47 new to score" would come back with 0 scored and no error (a *malformed* tool call, not an empty one, so nothing raised `JobScoringError`). Fixed by correlating on each job's **position in the batch** (a small integer, freshly numbered 0..N-1 per batch) instead of its `id` — Claude only ever echoes back a short index, never the opaque ID itself. This is also strictly better than the old id-echo scheme for the original cross-source-collision reason: positions can't collide regardless of what the underlying IDs look like, so the `_composite_key` helper that existed solely to prevent that collision was removed entirely. If you add a source whose IDs are large or unusual in some other way, this design already accommodates it — nothing about `job_scoring.py` looks at `id` at all anymore.

**Gotcha:** `MAX_TITLES` alone doesn't control how many titles the model returns — it only truncates the response afterward (`titles[:max_titles]`). The actual instruction to the model lives in the tool schema's field `description` string, which is a separate piece of text. Raising `MAX_TITLES` from 6 to 15 once had no effect because the schema description still hardcoded `"3-6 distinct job titles"` — Claude was told 6 and complied, regardless of what the code would have allowed through. Fixed by generating the schema (`_build_tool(max_titles)`) at call time so the description always states the actual `max_titles` in effect. Anywhere a numeric limit is enforced both in a prompt/schema *and* in code, changing only the code side is not enough — the two need to move together.

## Caching design

Two independent caches, both in `.cache/` (gitignored), both bypassable with `--no-cache`:

1. **CV criteria cache** (`.cache/cv_criteria/<sha256(cv_text)>.json`) — the extraction step is deterministic-ish given the same CV bytes, so there's no reason to re-parse the PDF or re-call Claude on every run of the same CV. Cache key is the CV's own content hash, so editing the CV automatically invalidates it — no manual cache-busting needed.
2. **Job score cache** (`.cache/scores/<cv_hash>.json`, keyed internally by `"source:job_id"`) — this is the higher-value cache. The same postings reappear across daily runs (a listing stays live for days/weeks), so re-scoring a job you've already seen wastes a call for no new information. `find_jobs.py` splits each run's listings into "already scored" (read from cache) and "new" (sent to Claude), and only new ones cost anything. As a side effect this doubles as a natural "what's new since last run" signal, which is really what a job-alert tool should be surfacing rather than re-showing the same shortlist every day.

Corrupt or missing cache files are treated as a plain miss (`cache.py`'s `_read_json` swallows `JSONDecodeError`/`OSError`) — caching is an optimization, never a correctness requirement, so a bad cache file should never crash a run.

## The `distance` parameter

Original problem: searching from a home location like Cheltenham returned nothing for roles in London, even though it's a realistic commute. Adzuna's `where` param does near-exact area matching by default — it doesn't imply a radius.

Confirmed empirically (live API test against Adzuna, `gb`, "Enterprise Architect" from Cheltenham):

| `distance` (miles) | Result count |
|---|---|
| unset / 1–20 | 0 |
| 30 | 1 |
| 50 | 5 |
| 80 | 54 (starts including London) |

So `distance` is a real radius parameter, in **miles**, measured **as the crow flies** (not drive/transit time — modeling actual commute time would need a separate API like Google's Distance Matrix, which is a bigger addition not built here). `find_jobs.py` defaults to `DEFAULT_DISTANCE_MILES = 25` when neither `--distance` nor a profile `max_commute_miles` is set, rather than leaving it unset.

Google Jobs' equivalent, `lrad`, is in **kilometers**, not miles — see the Google Jobs entry below for the conversion.

## Job sources

`find_jobs.py` defines a small `JobSource` protocol (`search(title, salary_min, location, max_results, distance=None) -> list[JobListing]`) implemented by `AdzunaSource` and `GoogleJobsSource`. Each wraps its module's `search_jobs()` function and produces the same shared `JobListing` shape. Google Jobs is opt-in — only added to the source list if `SERPAPI_API_KEY` is set, so the app works identically to before if you never get a key.

Dedup (`find_jobs.dedupe()`) and scoring correlation both key on `(source, id)` rather than bare `id`, since IDs from different sources can coincidentally collide — see the scoring-correlation gotcha above for how this interacts with Google Jobs' very different ID shape.

Adding another source is a matter of writing one more module with a `search_jobs()`-shaped function and one more thin `XSource` wrapper class in `find_jobs.py` — no changes needed to dedup or caching. If the new source has a much smaller quota than Adzuna's (like Google Jobs does), give it the same `titles_for_source()` treatment rather than letting it loop over every CV-derived title.

### Adzuna

Works as documented. No known issues.

### Google Jobs (via SerpApi)

Aggregates across many underlying boards (LinkedIn, Indeed, ZipRecruiter, company career sites, etc.) in one query — verified working end-to-end, including pagination via `serpapi_pagination.next_page_token` (10 results per page) and real apply links pointing at the actual source board, not a Google-owned URL.

Two real constraints, both handled deliberately rather than ignored:
- **No structured salary field.** Google Jobs doesn't reliably expose parsed salary data the way Adzuna does, so `JobListing.salary_min`/`salary_max` are always `None` for this source. `salary_min` filtering is applied client-side in `GoogleJobsSource.search()` (jobs with no salary data pass through rather than being excluded, since "unknown" isn't the same as "too low").
- **Quota is far more limited than Adzuna's free tier**, and metered per page fetched, not per app-level "search." `find_jobs.py`'s `GOOGLE_JOBS_MAX_TITLES` exists as a single, deliberately-tunable safety ceiling on how many CV-derived titles get searched through this source — but it's set well above `cv_extraction.MAX_TITLES` (50 vs. 15), so on an actual run it never bites; the "capped to top N titles" log line only appears when it would genuinely apply. Whether to tighten it back down is a per-user call depending on your own SerpApi plan size, not something to guess a "safe" default for. This cap is applied via `titles_for_source()`, a small pure function kept separate from the main search loop so it's independently testable rather than an inline `if isinstance(...)` buried in `main()`.
- **`max_results` defaults to 100** (`MAX_PAGES` × `RESULTS_PER_PAGE`, i.e. the actual pagination ceiling, not an arbitrarily smaller number) — `find_jobs.py`/`mcp_server.py` still pass their own `max_results_per_title` explicitly on every call regardless, so this only matters when calling `google_jobs_search.py` directly (its CLI or as a library).
- **`lrad`, not `distance`.** SerpApi's radius parameter is in kilometers, not miles like Adzuna — `google_jobs_search.py` converts the app's mile-based `distance` value internally so the CLI surface stays consistent across both sources.

**Gotcha (fixed): `location` must be a canonical string, not arbitrary free text.** The `google_jobs` engine 400s on location strings that don't exactly match one of Google's known locations — e.g. `"Cheltenham, Gloucestershire"` (a perfectly normal CV-derived location) was rejected outright, while the bare city `"Cheltenham"` resolves fine. Since `location` is usually either CV-derived text or a profile/CLI value with no guarantee it's in Google's exact format, `google_jobs_search.py` now resolves it through SerpApi's separate, free **Locations API** (`serpapi.com/locations.json`, no `api_key`/credits required) before searching: try the full string, then just the first comma-separated segment (usually the city name alone), and if neither matches, drop the `location` param entirely rather than send a string already known to fail. Resolution is memoized in-process (`functools.lru_cache`) since the same location repeats across every title in a run. Tests must clear that cache between cases (`_resolve_location.cache_clear()`) or results leak across tests.

### Removed: Reed

A Reed integration was built and later removed. It went through a third-party RapidAPI listing ("Reed.co.uk API" by `apidock-apidock-default`), not Reed's own developer portal — that switch happened because Reed's own key-request process never produced a working key. The RapidAPI listing's documentation looked complete, but in testing, every request — across multiple endpoints, with request bodies matching the provider's own documented examples exactly — returned an identical generic non-error response rather than real data, or a `429` from the free tier's rate limit despite never getting a successful response. 0 subscribers, 0 reviews, no discussion posts on the listing. Net effect was a source that contributed zero real listings while still spending a request per title and occasionally rate-limiting — pure overhead, no benefit — so it was pulled out entirely (`reed_search.py`, `ReedSource`, `REED_API_KEY`) rather than left wired in as dead weight. Worth remembering if a Reed source is ever revisited: verify a third-party API listing actually returns real data for a couple of real queries before building against its docs — matching documentation doesn't guarantee a functioning backend.

## Profile design

`setup_profile.py` asks a short, fixed set of questions once and writes `profile.json` (gitignored, like `.env`): max commute distance, remote-OK, willing-to-relocate, a salary floor override, excluded companies, and one free-text "anything else" field.

Structured fields over a fully freeform prompt, deliberately: a fixed `max_commute_miles` reliably maps onto the `distance` API parameter every time, whereas parsing "I don't want to travel too far" out of freeform text each run would be unreliable and wasteful (another Claude call, on every run, just to re-derive something that doesn't change between runs). The one open `notes` field is the pressure valve for anything the structured fields don't capture — it gets folded into whichever LLM prompt can act on it, as qualitative context rather than something machine-parsed.

The profile feeds three different downstream consumers:
- **Search parameters** (`distance`, `salary_min` override, `excluded_companies` post-filter) — deterministic, applied in `find_jobs.py` before any listings are fetched or after dedup, no LLM involved.
- **Title extraction** (`cv_extraction.extract_job_criteria(..., notes=profile.notes)`) — `notes` is passed alongside the CV text so Claude can broaden title selection beyond what's literally on the CV (e.g. "keen to leverage my CFA designation" pulls in finance-adjacent titles the CV itself never mentions). **This was missing in the first version** — `notes` only reached the scoring step, so a note asking for broader/different titles had no effect on what was actually searched, only on how already-fetched results were scored. Titles are generated once per CV+notes combination, so this only costs one extra call, not one per search.
- **Scoring prompt** (`job_scoring._preferences_block()`) — the same commute/remote/relocate/notes fields are also described to Claude during scoring, so a CV-perfect match that's on-site-only and two hours away can be scored down accordingly.

Because `notes` now affects title extraction, the CV-criteria cache key (`cache.cv_text_hash`) hashes `cv_text` **plus** `notes` together, not just the CV text — editing your profile notes invalidates the cached titles (and scores, which share the same hash) so a new extraction actually reflects the new notes, rather than silently serving stale titles computed before the notes existed.

## HTML report

The original CLI output was a multi-line-per-job dump to the terminal (title, salary, location, rationale, URL each on their own line) — fine for 3 results, unusable for 30+. `--html` writes one self-contained `results.html` instead: a single `<table>` with a client-side filter box and click-to-sort headers, no build step, no external CDN, no JS framework — just inline `<style>`/`<script>` in one file so it works fully offline.

A few implementation notes worth keeping in mind if this gets extended:
- **`html_report.py` takes plain `dict` rows, not `JobListing`/`ScoredJob` objects.** The three callers (`adzuna_search.py`, `google_jobs_search.py`, `find_jobs.py`, `mcp_server.py`) each convert their own dataclasses to dicts before calling `write_report()`. This keeps the report generator decoupled from which dataclass produced the data — it only cares about a handful of dict keys (`title`, `company`, `location`, `salary_min`/`salary_max`, `source`, `created`, `url`, `description`, optional `score`/`rationale`).
- **All text fields are HTML-escaped** (`html.escape`) before being interposed into the page — job titles/descriptions/company names are attacker-uncontrolled but still external data (from Adzuna/Google Jobs listings), so this isn't optional.
- **The filter listens on the `input` event, not `keyup`.** `keyup` misses paste, autofill, and some automated/synthetic typing — `input` fires for all of them. This was caught by testing the filter interactively in a browser rather than just checking the generated HTML string contained a `<script>` tag.
- Score column only renders when at least one row actually has a score (`show_score = any(row.get("score") is not None for row in rows)`), so unscored plain-search reports don't show an empty column.
