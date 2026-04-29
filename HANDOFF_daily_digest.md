# Handoff — Daily Digest

For Claude Code, in the wagon-watcher repo. Read this after the
price-history export is shipped and verified.

This is a small additive change. Adds a daily morning digest that
gets committed to the repo for the user (Patrick) to read on his
phone first thing in the morning. Same cadence pattern as the
existing weekly digest from step 8; different cadence, different
format, different audience question.

---

## What this adds

A new cron job and a new digest generator that produces:

```
digest/daily/2026-04-30.md
digest/daily/2026-05-01.md
...
digest/daily/LATEST.md  (symlink/copy of today's file)
```

One file per day, committed alongside the rest of the run output.
Readable on phone via the GitHub web UI; URLs are predictable for
external consumption.

## When it runs

**05:00 PT** = **12:00 UTC during PDT** (March-November) / **13:00 UTC during PST** (November-March).

Use the cron expression `0 12 * * *` and accept that the user reads
this at 5am during summer and 4am during winter. **Do not** try to be
clever with timezone-aware crons — GitHub Actions doesn't support
them and the DST shift is a one-day mild inconvenience, not a
recurring problem.

If the user wants to shift the cron after the first DST transition,
that's a one-line PR.

## Why 05:00 PT specifically

The user wakes up early. The digest needs to land before he reads
it. The European market closes at noon UTC and the US East Coast
dealers begin their day shortly after — by 12:00 UTC the prior
night's data is fully settled and the morning's first East Coast
listings are in. That's the right snapshot for a daily read.

## What goes in the digest

Six sections in this order. Each section starts with a `§` marker
matching the project's typographic conventions.

### § Population

One line summary:

```
Population: 36 active (-1 net since yesterday) · 4 watchlist matches · 1 actionable
```

"Actionable" = watchlist match + no known disqualifying flag. The
list of disqualifying flags is maintained as a small JSON file at
`config/disqualified_vins.json` — the user can edit this manually
when he confirms a Carfax issue (e.g., the Chicago wagon).

If `disqualified_vins.json` doesn't exist, treat all watchlist
matches as actionable.

### § Movers

Top 10 absolute % moves in the last 24 hours, sorted by magnitude.
Format:

```
- W1KLH6FB0SA147147 — Cary, NC — $65,980 (-$1,700 / -2.51%)
- W1KLH6FB5SA139657 — New Country, CT — $69,997 (-$2,000 / -2.78%)
- ...
```

Include both up and down moves. Use the existing 24-hour-window
delta logic from `reconcile.py`.

### § Floor watch

VINs currently at their all-time low since first-seen. Reads from
`price_history.json`'s `stats.all_time_low` and compares against
`current_price`. Format:

```
- W1KLH6FB0SA147147 — Cary, NC — $65,980 (down from $67,680 floor)
- ...
```

Limit to 5 VINs max. If more than 5 are at floor, suffix with
`... and N more at floor`.

### § Anomalies

Flag unusual things from the last 24 hours of operation:

- A dealer that toggled the same VIN in/out >2 times (signals feed instability or price-testing)
- Any cron run that took >60 seconds (signals API slowness)
- Any cron run that returned <30 listings (signals API cap or auth issue — normal pool is 36)
- A new dealer appearing for the first time
- Any VIN that moved between dealers (intra-network transfer)

Format as a short bulleted list. If nothing anomalous happened in
24h, output:

```
No anomalies detected in the last 24h.
```

This is genuinely useful as confirmation that the system is healthy.
Don't omit the section just because it's quiet.

### § Watchlist matches

For each active watchlist match, one line:

```
- W1KLH6FB9SA129598 — Chicago, IL — $61,516 — DISQUALIFIED (Carfax)
- W1KLH6FB0SA147147 — Cary, NC — $65,980 — pending Carfax
- W1KLH6FB5SA085762 — Smithtown, NY — $67,893
- W1KLH6FB1SA099139 — Okemos, MI — $66,500
```

Statuses to surface:
- `DISQUALIFIED (reason)` if VIN is in `disqualified_vins.json`
- `pending Carfax` if user has annotated it as such
- bare line otherwise

Annotations come from a manually-edited JSON file:
`config/vin_annotations.json` — same pattern as the disqualified
list. If this file doesn't exist, render bare lines.

### § Decision queue

The system's prompt for the user. Format:

```
Open decisions today:
- Cary VIN ...147147 — Carfax + window sticker request (3 days pending)
- Smithtown VIN ...085762 — first contact (5 days pending)
- ...

No new decisions surfaced.
```

This section requires the user to maintain a third small JSON file:
`config/decision_queue.json` — list of `{vin, action, opened_at,
closed_at}` entries. The digest renders open ones (closed_at is null)
and shows how long they've been pending.

If `decision_queue.json` doesn't exist or is empty, output:

```
No decisions in queue. Add one with: edit config/decision_queue.json
```

This is the section the user will check most often. Treat the file
format documentation in the digest's footer as part of the contract.

## Where it lives

```
digest/
├── LATEST.md               # weekly (existing, untouched)
├── 2026-W17.md            # weekly archive (existing)
├── ...
└── daily/                  # new
    ├── LATEST.md
    ├── 2026-04-30.md
    ├── 2026-05-01.md
    └── ...
```

The weekly digest from step 8 stays exactly as it is. The daily
lives in a sub-directory to keep the file lists separate.

## Implementation

New file: `digest_daily.py` (separate from existing `digest.py` to
avoid mixing concerns). Reuses helpers from `digest.py` where they
exist; copies them where they don't.

Signature:

```python
def generate_daily_digest(
    db_path: Path,
    output_dir: Path,
    config_dir: Path = Path("config"),
) -> Path:
    """Generate today's daily digest and write to output_dir.
    Returns the path written.
    """
    ...
```

Called from a new GitHub Actions workflow:

```yaml
# .github/workflows/digest_daily.yml
name: digest-daily
on:
  schedule:
    - cron: '0 12 * * *'  # 05:00 PT (12:00 UTC during PDT)
  workflow_dispatch:       # allow manual trigger for testing
jobs:
  digest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python -m wagon_watcher.digest_daily
      - name: Commit
        run: |
          git config user.name "wagon-watcher"
          git config user.email "watcher@noreply.local"
          git add digest/daily/
          git diff --staged --quiet || git commit -m "digest: daily $(date -u +%Y-%m-%d)"
          git push
```

Same git-add discipline as the existing watch workflow.

## Tests

Three tests:

1. **Empty DB produces a valid digest with all-zero counts** — graceful
   handling of fresh deploy
2. **Fixture DB with synthetic movers produces correct § Movers
   section** — verify sort order, format, and 10-row limit
3. **Disqualified VIN renders correctly** — given a fixture
   `disqualified_vins.json`, verify the watchlist line shows
   "DISQUALIFIED (reason)"

Mirror the test patterns from the existing weekly `digest.py`
tests.

## Out of scope for this handoff

- No Pushover alert when the digest lands. The digest is read on
  the user's schedule, not pushed.
- No HTML rendering. Markdown only — GitHub renders it on phone
  cleanly.
- No charts or sparklines in the digest. Numbers and prose only;
  visual analysis lives in dashboard v2.
- No retention policy on old daily digests. Git history is the
  archive. Revisit if file count crosses 1000+.
- No conditional skipping. The digest runs every day regardless of
  whether anything interesting happened — the user wants the
  consistency of "5am file always exists."
- No mobile-formatting hacks. GitHub's mobile markdown rendering
  is good; trust it.

## Commit hygiene

Two commits suggested:

1. `digest_daily: new daily digest generator with movers, floors, anomalies, watchlist, decision queue`
2. `ci: add digest-daily workflow at 05:00 PT (12:00 UTC)`

Each leaves the system in a working state.

---

## Verification after deploy

1. Manually trigger the workflow once via `workflow_dispatch` to
   verify the first run works
2. Verify `digest/daily/LATEST.md` and `digest/daily/2026-04-30.md`
   (or whatever today's date is) appear in the repo
3. Open the file on phone via GitHub mobile, confirm it renders
   readably
4. Wait for the next scheduled run (5am PT next day) to verify the
   cron triggers correctly
5. Verify no error if `config/disqualified_vins.json`,
   `config/vin_annotations.json`, or `config/decision_queue.json`
   don't exist — they should be optional

If all five pass, the daily digest is shipped and the user has a
new morning routine.

Total scope: roughly 60 minutes including tests. The bulk of the
work is the formatting templates; the data fetching is mostly
reused from existing code.
