# Future: scheduled/background mode with the Batches API

A design sketch, not implemented. Captures the reasoning from "is the Batches API worth it?" so it doesn't need re-deriving later. See [ARCHITECTURE.md](ARCHITECTURE.md) for how the current synchronous app works.

## Why this is a separate mode, not a flag on `find_jobs.py`

The [Batches API](https://platform.claude.com/docs/en/build-with-claude/batch-processing) is async — submit a batch, then poll until `processing_status == "ended"` (typically within an hour, up to 24h). That's fundamentally incompatible with `find_jobs.py`'s current shape: run the command, get the HTML report seconds later. Bolting Batches onto that command would mean it submits and exits, and you'd have to come back later to fetch results — worse UX for the interactive case for no benefit (a manual run is a handful of cents either way).

So: **the existing synchronous path stays exactly as it is** for on-demand use (`find_jobs.py`, the MCP tools). This is a new, separate entry point for the case where nobody's watching in real time and there's enough volume for the 50% discount to matter — a nightly/scheduled alert rather than an interactive query.

## What changes vs. today

| | Today (`find_jobs.py`) | Scheduled mode |
|---|---|---|
| Trigger | You run it | Cron/Task Scheduler, unattended |
| CV extraction | Sync call, cached by `cv_hash` | Same — still cached, still sync (it's one call, batching buys nothing here) |
| Job scoring | Sync, batches of 40 per Claude call, sequential | Submitted as one Batches API call containing many 40-job requests; polled once later |
| "What's new" | Score cache tells you what's already scored | Needs a **seen-postings ledger**, not just a score cache (see below) |
| Output | `results.html`, overwritten each run | Timestamped report + some notification that it's ready |
| Cost | A few cents per run, paid per invocation | Same per-job cost minus 50%, but batched into fewer, larger charges |

## Flow

```
Cron fires (e.g. nightly at 02:00)
  │
  ▼
scheduled_run.py
  │  load profile.json, CV path from config
  │  extract_text() + extract_job_criteria()   — cached, so free/instant most nights
  │  search every source × title (as today)     — Adzuna/Google Jobs, no Claude cost
  │  dedupe()
  │  filter against seen-postings ledger         — NEW: postings already surfaced in a
  │                                                 prior run, even if not yet scored,
  │                                                 don't need to be re-submitted
  ▼
batch_scoring.py (new)
  │  chunk new listings into groups of MAX_JOBS_TO_SCORE
  │  submit ONE Batches API call containing all chunks as separate requests
  │  (custom_id per chunk so results can be matched back)
  ▼
  [ up to ~1h later, or on next scheduled tick ]
  │
  ▼
  poll batch → retrieve results → merge into score cache (same cache.py, same shape)
  update seen-postings ledger
  write dated report (reuse html_report.py)
  notify (see "open question" below)
```

## Batches API specifics

- One batch = many independent Messages API requests, each with its own `custom_id`. A batch can hold up to 100,000 requests / 256MB — comfortably more than this app will ever produce in a night.
- Each request in the batch is still shaped like today's per-batch scoring call (CV text + up to 40 job summaries + tool-forced scoring) — the 40-per-request chunking in `job_scoring.py` doesn't go away, it's just that N chunks become N *parallel* requests inside one batch instead of N *sequential* synchronous calls.
- Results arrive in **any order** — key by `custom_id`, same caution as the general Claude API guidance, not something to relearn later.
- 50% discount applies to every token in the batch, same pricing model otherwise (Haiku 4.5, same $1/$5 per million).
- Batch results are retrievable for 29 days — plenty of headroom for a "check back tomorrow" cron.

## The bigger unlock: a seen-postings ledger

Today's score cache (`(cv_hash) → {source:id → score}`) already avoids re-scoring a job you've seen before. Scheduled mode wants one more layer: a **ledger of postings already surfaced to you**, independent of whether they were scored, so:

- The first scheduled run after setup will likely have a real backlog (potentially 100+ new listings across titles/sources) — this is exactly the volume where Batches' 50% + parallelism pays for itself.
- Every run after that should mostly be "what's posted since last night," which is usually small — the point of a job *alert*, not a full re-scan shown to you every time.

This ledger is a natural extension of `cache.py`, not a new subsystem — likely `.cache/seen/<cv_hash>.json` listing `source:id` keys already reported, checked before scoring (not instead of the score cache — a posting can be "seen but not yet scored" if a previous run's batch was still processing when the report was generated).

## Open question: notification

Nobody's watching a terminal for this. Options, roughly in order of setup effort:

1. **Just write the file** — timestamped `results/2026-08-01.html`, check it yourself when convenient. Zero extra moving parts, but "unattended" only in the sense that nothing crashes if you don't look — it's not actually pushing anything to you.
2. **Desktop notification** on the machine running the cron (toast notification with a count of new matches).
3. **Email** — send the report or a summary via SMTP.
4. **Slack/webhook** — post a summary with a link to the local report.

This should be picked based on how "hands-off" you actually want it, not decided in advance — flagging it here rather than guessing.

## Trigger mechanism

Two real options:

- **OS-level scheduler** (Windows Task Scheduler, since this runs on Windows) invoking `python scheduled_run.py` directly on a cron-like schedule. Simplest, no dependency on any Claude product being open, easiest to reason about and debug (it's just a scheduled process).
- **A Claude Code scheduled/cloud agent** (the `CronCreate`/scheduled-routine tooling available in this environment) running the same logic as an agent session on a schedule instead of a plain script. Only worth it if you want Claude *itself* orchestrating the run (e.g. deciding what to do with ambiguous results) rather than a deterministic script — for this app's actual logic (search → dedupe → batch-score → report), a plain scheduled script is simpler and cheaper than a full agent session, since there's no open-ended reasoning needed at runtime.

Recommendation: start with the OS scheduler running a plain script. It's the smaller, more debuggable piece, and nothing about this design depends on the more complex option.

## Rough implementation phases (whenever this gets picked up)

1. `batch_scoring.py` — submit/poll/retrieve wrapper around the Batches API, same input/output shape as today's `job_scoring.score_jobs()` (so callers don't care which one they're using).
2. Seen-postings ledger in `cache.py`.
3. `scheduled_run.py` — the orchestration script described above, reusing `find_jobs.py`'s search/dedupe/profile logic (refactor shared pieces out if `find_jobs.py`'s `main()` doesn't already expose them as importable functions).
4. Pick a notification mechanism (start with "just write the file," upgrade later if the hands-off gap actually bothers you in practice).
5. Wire up the OS scheduler.

## Non-goals for v1 of this mode

- No need to solve arbitrary failure/retry logic for a batch that never completes — the existing 29-day retrieval window and a simple "if not ended, try again next tick" is enough for a personal tool.
- No need for a fancy job history UI — a folder of dated HTML reports is enough to start.
- No need to unify the sync and batch scoring code paths beyond sharing a return shape — keeping them as two separate, simple implementations (`job_scoring.py` and `batch_scoring.py`) is preferable to one complicated function branching on mode.
