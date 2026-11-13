# job-hunter

Personal job alert tool. Searches Adzuna (and optionally Google Jobs) by title/salary/location, and can turn a CV PDF into search criteria and a ranked shortlist via Claude.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how it's built, what each piece does, what costs money, and the reasoning behind the caching/distance/profile design.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` — free at [developer.adzuna.com](https://developer.adzuna.com/)
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com) (Settings → API Keys). This is a separate, pay-as-you-go product from a Claude Pro/Max subscription.
- `SERPAPI_API_KEY` — optional. From [serpapi.com](https://serpapi.com) (paid; small free tier). Adds Google Jobs, which aggregates many underlying boards in one query. Only your top few CV-derived titles are searched through this source (`GOOGLE_JOBS_MAX_TITLES` in `find_jobs.py`) to protect the quota — see ARCHITECTURE.md.

Optionally set up a saved profile (commute radius, salary floor, excluded companies):

```bash
python setup_profile.py
```

## Usage

### Manual search

```bash
python adzuna_search.py --title "data engineer" --salary-min 120000 --location "Seattle, WA" --distance 25
python google_jobs_search.py --title "data engineer" --location London --distance 25
```

`--location`, `--salary-min`, and `--distance` are all optional. `--distance` is a search radius in miles around `--location` — without it, Adzuna defaults to tight, near-exact-area matching, so a nearby but non-identical location (e.g. a commutable city) may return nothing. `--country` (Adzuna only) defaults to `us` (also supports `gb`, `au`, `ca`, `de`, etc.).

### CV-driven search

Give it a CV PDF instead of a title. Claude infers candidate search titles, a suggested location, country, and salary floor from the CV; each title is searched against every enabled source (Adzuna, plus Google Jobs if `SERPAPI_API_KEY` is set — capped to your top few titles) and the results are deduped.

```bash
python find_jobs.py --cv resume.pdf
python find_jobs.py --cv resume.pdf --location "Austin, TX" --salary-min 150000 --json
python find_jobs.py --cv resume.pdf --score
```

Precedence for `--location` / `--salary-min` / `--country` / `--distance`: **explicit CLI flag > saved profile (`profile.json`) > CV-derived suggestion > built-in default**. If you've run `setup_profile.py`, its `excluded_companies` are filtered out of every result automatically.

Add `--score` to rank the deduped results by fit against the CV (via Claude), with a one-sentence rationale per listing — this also factors in your saved profile's commute/remote/relocation preferences if present.

CV extraction and job scoring are both cached (keyed on CV content and on `source:job_id` respectively) so repeat runs with the same CV skip redundant Claude calls. Pass `--no-cache` to bypass both.

### HTML report

All three scripts (`adzuna_search.py`, `google_jobs_search.py`, `find_jobs.py`) support `--html` in place of the terminal dump — writes a single self-contained `results.html` (sortable columns, a filter box, clickable job links, and score/rationale when scoring is on) instead of printing:

```bash
python find_jobs.py --cv resume.pdf --score --html
python find_jobs.py --cv resume.pdf --score --html --html-output my_matches.html
```

Open the file in any browser — no server, no dependencies.

## MCP server

`mcp_server.py` exposes two tools over MCP: `search_adzuna_jobs` (single-title search) and `find_jobs_from_cv` (the full CV → titles → multi-source search → dedupe → score pipeline, with the same caching and profile behavior as the CLI). Pass `html_output="path.html"` to `find_jobs_from_cv` to also write the HTML report alongside the structured result.

Run it directly:

```bash
python mcp_server.py
```

To use it from Claude Desktop or Claude Code, add it as an MCP server, e.g. in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "job-hunter": {
      "command": "python",
      "args": ["C:\\Users\\cshep\\source\\job-hunter\\mcp_server.py"]
    }
  }
}
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

All tests mock Adzuna/Google Jobs/Claude — no live API calls or credentials required to run them.
