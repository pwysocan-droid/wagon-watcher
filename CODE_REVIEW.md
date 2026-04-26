# Code Review Notes — wagon-watcher

Reviewed: 2026-04-26
Reviewer: Claude (claude.ai project chat)
Repo: github.com/pwysocan-droid/wagon-watcher
Files reviewed: db.py, scrape.py
Files NOT yet reviewed: reconcile.py, run.py, .github/workflows/, migrations/*.sql, tests/

---

## Verdict

The build is in good shape. Architecture follows PROJECT.md, separation of
concerns is clean, and the team caught a legitimate API quirk during
implementation that the original recon missed. Two follow-up items below
are tracked as TODO, not blocking.

This document is for Claude Code to read in a future session. It captures
both the things to keep doing and the things to address. Read it before
making changes to scrape.py, db.py, or reconcile.py.

---

## Things to keep doing

### 1. Comment the *why*, not just the *what*

The `COUNTS_FOR_UNION` block in scrape.py is the model. Eight lines of
prose explaining: what the API does, what the original recon got wrong,
what the empirical behavior actually is, and why the union strategy is
deterministic. Anyone reading the file in 6 months — including future
Claude Code instances — gets the full context inline.

Apply the same standard to any future workaround for an API quirk,
schema decision, or reconciler edge case. If a comment would only
restate the code, skip it. If it would explain a non-obvious decision,
write it.

### 2. Pure parsing, side-effecting orchestration

`parse_record` and `parse_response` are pure functions of their input.
`fetch_all` has the network side effect. `save_snapshot` has the
filesystem side effect. `main()` orchestrates. This separation makes the
parser testable against fixtures without ever hitting the network and
without ever touching the DB. Maintain this boundary. If a future change
needs to add DB reads or writes inside parsing, push that logic into the
reconciler instead.

### 3. Treat the API's own metadata as untrusted

The code already does this in two places:

- `success: false` or `status.code != 200` → raise (abort signal).
- The API's `paging.totalCount` is overridden after the union because it
  was empirically wrong.

Continue this posture. The MBUSA API is a public marketing surface; its
internal consistency is not a guarantee. If the API ever returns a
`success: true` payload with garbage records, the reconciler's health
check (50% drop threshold per PROJECT.md) is the second line of defense.

### 4. Live data lives under `usedVehicleAttributes`

This is the most consequential parsing decision in the codebase. Record
root has partial data on records #2 onwards; the full per-vehicle data
is nested in `record.usedVehicleAttributes`. The current `parse_record`
correctly pulls dealer, mileage, and certified-flag from `uva`, with
fallbacks to record root for the fields that *are* reliable there
(VIN, year, modelName, modelId, bodyStyleId, msrp, paint, upholstery,
exteriorMetaColor).

Do NOT change this without re-validating against the fixture. Specifically:

- `record.mileage` exists at root only on the first record in some
  responses. Always read `uva.get("mileage")` first.
- `record.dealer` exists at root but may be a thinner version than
  `uva.get("dealer")`. Prefer `uva` for the canonical dealer object.
- `record.images` is the same story — prefer `uva.get("images")` for
  the real-photo array; `record.exteriorBaseImage` is the stock IRIS
  render, which is not what we want for notifications.

If MBUSA ever fixes their API to be consistent at root, this logic will
keep working (uva will be redundant but not wrong). If they break it
further, fail loudly rather than silently degrading.

---

## TODO 1 — Add a sanity-check threshold to fetch_all

**Where:** `scrape.py`, after the union loop in `fetch_all()`, before
the synthetic response is built.

**Why:** The union strategy assumes `count=12` and `count=24` return
disjoint windows. If MBUSA changes the backend so both return the same
records (the most likely silent-failure mode), the watcher would
quietly lose ~24 cars from its dataset. The health check in the
reconciler catches a 50% drop run-over-run, but only after the first
bad run is already logged. Catching it inside the scraper is cheaper.

**What:**

```python
# After the union loop, before building the synthetic response:
EXPECTED_MIN_POOL = 25  # E450S4 wagon pool has been ≥34 nationally
                        # since recon. <25 indicates pagination broke.
if len(by_vin) < EXPECTED_MIN_POOL:
    raise RuntimeError(
        f"fetch_all returned {len(by_vin)} records, below expected "
        f"minimum {EXPECTED_MIN_POOL}. Pagination strategy may have "
        f"broken; verify count=12 and count=24 still return disjoint "
        f"windows. Aborting before reconcile."
    )
```

**Why a hard raise instead of a logged warning:** the watcher's main
risk profile is *silent* dataset corruption, not *visible* downtime.
Failing loud means the GitHub Action shows red, the user investigates,
and the DB stays clean. Failing soft means months of half-data that's
hard to detect. Per PROJECT.md health-check rule: abort, don't corrupt.

**Constant naming:** make `EXPECTED_MIN_POOL` a module-level constant
near `COUNTS_FOR_UNION`, not a magic number inside the function. Future
us will want to tune it as the market evolves (e.g., if 2026-model
year arrivals push the pool to 50+, the threshold should be higher).

---

## TODO 2 — Confirm observed_at provenance in reconcile.py

**Where:** `reconcile.py` (not yet reviewed in this session).

**Why:** `ParsedRecord` correctly does NOT carry an `observed_at`
timestamp — that's a reconciler concern, not a parser concern, and
parsing should remain pure. But the schema (per PROJECT.md) requires
`observed_at` on every `price_history` row.

**What to verify:**

1. The reconciler captures `datetime.now(timezone.utc)` once per run,
   not per-record (so all rows in a single run share a timestamp).
2. The timestamp is captured at the moment the API response was
   received, not at write time. (Receive time is more accurate. If the
   reconciler runs slowly, write-time would drift.)
3. The timestamp comes from the scraper's `save_snapshot` call or
   from a `runs` table row created at fetch time, not from a fresh
   `datetime.now()` inside the reconciler.

**If reconcile.py is doing it right:** add a one-line comment above
the timestamp source confirming the decision, in the same prose-style
as the COUNTS_FOR_UNION block. If it's wrong, fix it before the next
live run.

---

## TODO 3 (deferred, not blocking) — Health-check log line

**Where:** `scrape.py` `main()`, before the JSON dump.

**Why:** The current `main()` prints record counts to stderr, which is
correct for human runs. For automated runs in CI, stderr ends up in
the GitHub Actions log, but it's hard to grep across runs. A
machine-parseable log line in addition to the human-readable one
would make weekly digest generation easier.

**What:**

```python
import logging
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scrape")
log.info("scrape_complete records=%d totalCount=%s snapshot=%s",
         len(parsed), paging.get('totalCount'), snap.name)
```

The `key=value` format is grep-friendly and is the same pattern Datadog
and most observability tools expect. Defer this until step 8 (digest
work) — no urgency, just a quality-of-life improvement.

---

## Architecture observations (no action required)

**The `ParsedRecord` dataclass is the right granularity.** It mirrors
the watcher's domain model, not the API's wire format. Schema changes
on MBUSA's side don't ripple past `parse_record`. Schema changes on
ours don't ripple past the dataclass. Keep this boundary tight.

**The `connect()` helper sets WAL and FK pragmas on every connection.**
Correct for SQLite — these pragmas are per-connection, not persisted.
If a future change adds connection pooling or a context manager wrapper,
preserve both pragmas.

**The migration runner pairs up/down files by version prefix.** This is
correct and supports the `python db.py down N` workflow for rolling
back. Don't introduce schema changes that lack a paired down migration,
even if the down is a no-op CREATE/DROP — the runner enforces this with
a `RuntimeError`, which is the right behavior.

**The Python 3.12 datetime adapter registration** in db.py is a subtle
but important fix. Python 3.12 deprecated the default datetime adapter
because it produced ambiguous results. The explicit ISO-8601 adapter
silences the DeprecationWarning AND ensures timestamps remain
human-readable when the .db file is inspected with `sqlite3` CLI. Don't
remove it on a future cleanup pass.

---

## Things NOT to do

These are anti-patterns that PROJECT.md and the Feb decision-log warned
against. Listing here so future Claude Code sessions can pattern-match.

- **Do not introduce a Helvetica fallback** anywhere in the design
  layer (digest CSS, dashboard CSS, notification embeds). Per
  PROJECT.md: Inter is the open-source default. The full prohibited
  list is GT America / Söhne / PP Neue Montreal / ABC Diatype as
  primary, Inter as fallback, system-ui as ultimate fallback. No
  Helvetica, Helvetica Neue, or Arial.
- **Do not introduce a second accent color.** SBB Red (#EB0000) is the
  only color signal. No green-for-good, no yellow-for-warning. Status
  differentiation comes from typography, not from a palette expansion.
- **Do not paginate via `start`.** The API claims to support it but
  doesn't, per the recon update. Use the `COUNTS_FOR_UNION` strategy
  exclusively.
- **Do not write to `data/inventory.db` from `scrape.py`.** That
  module is pure with respect to the DB. All writes happen in
  `reconcile.py`. Keep this separation.
- **Do not commit `data/inventory.db` from a failed run.** The
  workflow should commit only after the reconciler exits 0. If the
  health check aborts, the run exits non-zero and no commit happens.
- **Do not exceed 30-minute polling.** The cron is set to `*/30` for
  reasons covered in PROJECT.md (politeness + sufficient temporal
  resolution for inventory that turns over in days). Don't tighten
  this loop.

---

## Build progress check (as of 2026-04-26)

Per PROJECT.md build order, the visible state is:

- ✅ Step 1 — Schema + migrations in db.py
- ✅ Step 2 — scrape.py against fixture (DRY_RUN works) and live
- ⚠️  Step 3 — reconcile.py exists but not reviewed in this session
- ❓ Step 4 — GitHub Action workflow (file exists in
              .github/workflows/ but content not reviewed)
- ❌ Step 5 — Notifications (no notify.py in the tree yet)
- ❌ Step 6 — fairprice.py
- ❌ Step 7 — VIN decode + geo enrichment
- ❌ Step 8 — Weekly digest
- ❌ Step 9 — Watchlist + Tier 2/3 notifications
- ❌ Step 10 — Cross-source price discrepancy detection

When step 4 is confirmed working with the 48-hour silent run, proceed
to step 5. Do not skip ahead.

---

## Suggested commit message for the TODO 1 fix

```
scrape: add minimum-pool sanity check to fetch_all

The union strategy (count=12 ∪ count=24) assumes the API returns
disjoint windows. If MBUSA changes the backend so both calls return
identical records, we'd silently lose ~24 cars from the dataset.

Add a hard threshold (EXPECTED_MIN_POOL = 25) that aborts the run if
the union produces fewer records than the established floor. The
reconciler's health check would catch this run-over-run, but failing
inside the scraper means we never log a partial run to the runs table.

Per PROJECT.md health-check rule: abort, don't corrupt.
```

---

## End of review

Future Claude Code: read PROJECT.md first, then this file. Then look
at any specific module you're about to change.
