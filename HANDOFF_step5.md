# Handoff Note — Step 5

For Claude Code, in the wagon-watcher repo. Read this before doing
anything else.

---

## Where we are

**Step 4 is complete.** The 48-hour silent run cleared cleanly:
- 23 consecutive successful runs
- 0 failures
- Run durations 11–22s, no drift
- Cron firing reliably (slower than `*/30` due to GitHub Actions
  free-tier throttling, which is fine — see below)

This means: the scrape → reconcile → commit-back pipeline is
stable. Time to add notifications.

## Updated files in this handoff

Two files in this packet supersede whatever's currently in the
repo:

- **`PROJECT.md`** — updated 2026-04-27. Notification channel
  locked to Pushover (was previously listed as Pushover/Discord/
  ntfy). Tier-to-priority mapping defined. Setup instructions
  added.
- **`CODE_REVIEW.md`** — adds TODO 4 (bump GitHub Actions
  versions from Node 20 to Node 24), discovered during the
  silent run. Non-blocking but should be bundled with the next
  workflow change.

Drop both into the repo root. Commit them as their own commit
with message `docs: update PROJECT.md (Pushover lock-in) and
CODE_REVIEW.md (TODO 4)` before starting the build work below.

## What to build (step 5)

Per the Notification rules section in `PROJECT.md`, build a
notification system on Pushover. Tier 1 only for now; Tier 2 and
Tier 3 wait for later steps.

### Prerequisites already done by the user

The user (Patrick) has:
1. Created a Pushover account
2. Created an Application/API Token named `wagon-watcher`
3. Added two secrets to GitHub Actions:
   - `PUSHOVER_USER_KEY`
   - `PUSHOVER_API_TOKEN`

If for any reason these aren't in place when you try to use them,
stop and surface that — don't try to work around missing secrets.

### Build order for this step

1. **Migration: add `notifications` table.** New paired
   `.up.sql`/`.down.sql` migration following the existing pattern.
   Schema:
   ```sql
   CREATE TABLE notifications (
     id INTEGER PRIMARY KEY,
     sent_at TEXT NOT NULL,
     tier INTEGER NOT NULL,
     event_type TEXT NOT NULL,
     vin TEXT,
     title TEXT NOT NULL,
     body TEXT NOT NULL,
     url TEXT,
     pushover_priority INTEGER NOT NULL,
     pushover_response TEXT,
     success INTEGER NOT NULL DEFAULT 0
   );
   CREATE INDEX notifications_recent ON notifications (sent_at DESC);
   ```
   Test migration up/down following the existing pattern.

2. **Migration: seed one watchlist row.** Per `PROJECT.md` the
   watchlist table must have at least one entry for Tier 1 alerts
   to fire. Seed the standing criteria:
   ```sql
   INSERT INTO watchlist (kind, spec_json, label, created_at, active)
   VALUES (
     'spec',
     '{"min_year":2024,"max_mileage":15000,"max_price_all_in":68000,"trim":"E450S4","body_style":"WGN"}',
     'Within criteria.md',
     datetime('now'),
     1
   );
   ```
   This represents what would have triggered the alert for the
   Keyes wagon (VIN W1KLH6FB6SA153938) had the watcher been live
   when it appeared.

3. **`notify.py` — Pushover dispatcher.** Single module exposing:
   ```python
   def send(
       tier: int,
       event_type: str,
       title: str,
       body: str,
       vin: str | None = None,
       url: str | None = None,
       image_url: str | None = None,
   ) -> bool
   ```
   Function:
   - Reads `PUSHOVER_USER_KEY` and `PUSHOVER_API_TOKEN` from env
   - Maps tier → Pushover priority per `PROJECT.md`:
     - Tier 1 + event_type='scraper_aborted' → priority 2 with
       `retry=30, expire=3600`
     - Tier 1 (other) → priority 1
     - Tier 2 → priority 0
     - Tier 3 → priority -2
   - POSTs to `https://api.pushover.net/1/messages.json`
   - 10-second timeout, 1 retry on connection error
   - Logs every send to the `notifications` table (success or
     failure of the POST itself)
   - Returns True on 2xx, False otherwise — does NOT raise
   - Honors `PUSHOVER_ENABLED` env var (default true); if false
     or `DRY_RUN` is set, prints the payload to stderr and writes
     a row to `notifications` with `success=0` and a synthetic
     "DRY_RUN" response

   The function should NEVER raise an exception that propagates
   out of `notify.send()`. Notification failures must not crash
   the reconciler.

4. **Wire into `reconcile.py`.** Four Tier 1 call sites:

   - **Watchlist match.** When a NEW listing matches any active
     watchlist entry, call `notify.send(tier=1,
     event_type='watchlist_match', ...)`. Match logic: read the
     `spec_json`, evaluate against the listing's year/mileage/
     price/trim/body. The match is OR across watchlist rows, AND
     within a row's spec.

   - **Price drop ≥7%.** When a known VIN's price drops by ≥7%
     vs its most recent prior price in `price_history`, call
     `notify.send(tier=1, event_type='price_drop_major', ...)`.

   - **Reappeared VIN.** When a VIN currently marked `gone` in
     `listings` shows up again in fresh API results, call
     `notify.send(tier=1, event_type='reappeared', ...)` — and
     update the listing's status to `active`.

   - **Scraper aborted.** This one fires from `run.py` (or
     wherever the health-check abort lives), not `reconcile.py`.
     `notify.send(tier=1, event_type='scraper_aborted', ...)`
     with priority 2.

5. **Update `watch.yml`** to expose the Pushover secrets to the
   workflow:
   ```yaml
   env:
     PUSHOVER_USER_KEY: ${{ secrets.PUSHOVER_USER_KEY }}
     PUSHOVER_API_TOKEN: ${{ secrets.PUSHOVER_API_TOKEN }}
     PUSHOVER_ENABLED: "true"
   ```

6. **Bundle TODO 4 with the workflow change.** While editing
   `watch.yml`, also bump:
   - `actions/checkout@v4` → `actions/checkout@v5`
   - `actions/setup-python@v5` → `actions/setup-python@v6`

   This is non-functional but takes care of the Node 20
   deprecation warning. Per `CODE_REVIEW.md` TODO 4: "do NOT
   make a dedicated commit for this; bundle with the next
   substantive workflow change." This counts.

7. **Tests.** Use `pytest` + `httpx` mocking (the project
   already has these per `requirements-dev.txt`). Tests to write:
   - `notify.send` with `PUSHOVER_ENABLED=false` writes a
     dry-run row and returns True
   - `notify.send` for tier=1 produces a POST with priority=1
   - `notify.send` for tier=1 + event_type='scraper_aborted'
     produces priority=2 with retry/expire fields set
   - `notify.send` on 4xx/5xx returns False, writes
     `success=0` row, and does NOT raise
   - `reconcile.py` — fixture-driven test where a synthetic
     "new VIN matching watchlist spec" produces exactly one
     `notify.send` call with tier=1, event_type='watchlist_match'

## Testing the integration end-to-end

After all of the above passes unit tests, do ONE manual end-to-
end test before declaring step 5 done:

1. Set `PUSHOVER_ENABLED=true` locally
2. Run `python notify.py --test` (you'll need to add this CLI
   entrypoint) — sends a real test notification with title
   "wagon-watcher integration test"
3. Confirm with the user that the notification arrived on their
   iPhone within 10 seconds
4. Only then push the workflow change

If the integration test fails, fix before pushing. A broken
notification path that ships into production silently swallowing
alerts is the single worst failure mode for this project.

## What to do if you get stuck

The patterns to follow are already in the codebase:

- Migration pattern → look at existing `migrations/` files
- DB connection pattern → use `db.connect()`, don't roll your own
- Test fixture pattern → look at how `tests/test_scrape.py`
  uses `fixtures/sample_response.json`
- Logging style → look at the comment density in `scrape.py`'s
  `COUNTS_FOR_UNION` block; match that level of why-not-what

If something genuinely can't be resolved by reading the existing
code or this handoff note, stop and surface to the user with a
specific question. Don't guess.

## Out of scope for step 5 (don't do these)

- Tier 2 notifications (later step, after step 7 digest is built)
- Tier 3 silent-history events (later step)
- Discord/email/SMS channels — explicitly rejected per the
  "Why Pushover" section in `PROJECT.md`
- A Pushover-receipt polling loop for priority-2 acknowledgments
  (Pushover handles this server-side; we just need to set the
  retry/expire flags)
- Notification rate-limiting (no value yet — at current data
  volume there are 0–2 events per day)
- A notifications dashboard UI (later, with the digest work)

## Commit hygiene

Suggested commit sequence for this work:

1. `docs: update PROJECT.md (Pushover lock-in) and CODE_REVIEW.md`
2. `db: add notifications table and watchlist seed`
3. `notify: add Pushover dispatcher with dry-run mode and audit log`
4. `reconcile: wire Tier 1 notifications for watchlist match,
    price drop ≥7%, and reappeared VIN`
5. `run: wire scraper-aborted notification with priority 2`
6. `ci: bump checkout@v5 and setup-python@v6, expose Pushover
    secrets to workflow`
7. `tests: cover Pushover dispatcher and reconcile notification
    paths`

Each commit should leave the system in a working, testable
state. If you find yourself wanting to amend a previous commit,
prefer a new commit with a clear message instead.

---

Total scope: roughly 60–90 minutes of work. Smaller than steps
1–3 because the architecture is already there; you're just
adding one module, one table, one seeded row, and four call
sites.
