# Amendment to Step 5 — Alert Log

For Claude Code, in the wagon-watcher repo. Read this after step 5
notifications are working and committed. This is a small additive
change, not a refactor.

---

## What this adds

A human-readable, version-controlled audit trail of every Pushover
alert the watcher sends, committed to the repo as markdown files.

The Pushover notification stays exactly as it is — this doesn't
replace it. It runs alongside, producing a parallel record that
lives in git history rather than only on the user's phone.

## Why

Three reasons:

1. **Audit trail.** Pushover's notification history is bounded
   (free tier ~30 days, app-side). Git history is forever. Six
   months from now the user can scroll back through alerts and
   see what the watcher caught.
2. **Off-device readability.** The alert files are markdown in a
   public repo, so they can be read by anyone with the URL —
   including Claude in claude.ai conversations, which can web_fetch
   raw.githubusercontent.com URLs but cannot read Pushover.
3. **Reproducibility.** When debugging "why did this notification
   fire," the markdown record is human-readable; the
   `notifications` DB table is structured but harder to scan.

## What to build

### File location and naming

```
alerts/
├── 2026-04-28.md
├── 2026-04-29.md
└── ...
```

One file per UTC day. Lazy-create on first alert of the day. Files
are append-only.

### File format

Markdown with a stable structure so future tooling (digest
generation, search, analysis) can parse it. Each alert is one
section delimited by a hairline rule.

```markdown
# Alerts — 2026-04-28

§ 14:23:41 UTC · Tier 1 · watchlist_match
**2025 E450 4MATIC All-Terrain** · [W1KLH6FB6SA153938](https://www.keyesmercedes.com/inventory/...)
- Asking: $65,895
- Mileage: 13,418
- Dealer: Keyes European (Van Nuys, CA · 10 mi from 90210)
- Days on lot: 4
- Body: Within criteria.md · 2024+ · ≤15k mi · in-region match. Cheapest qualifying 2025 wagon in California.

---

§ 09:14:08 UTC · Tier 2 · price_drop_minor
**2024 E450 4MATIC All-Terrain** · [W1KLH6FB1RA061291](https://www.smothers.mercedesdealer.com/inventory/...)
- Was: $70,500 → Now: $67,000 (−4.96%)
- Dealer: MB Santa Rosa (CA · 397 mi from 90210)
- Days on lot: 22
- Body: Now within $1,755 of Keyes for same Obsidian Black colorway.

---
```

Format rules:

- **Section marker `§ HH:MM:SS UTC · Tier N · event_type`**
  matches the SBB-style section markers used elsewhere in the
  project's design language. Not bold, set in plain text — the
  marker carries the structure.
- **Year/trim line** uses the VIN as a markdown link to the
  dealer URL. This honors the project's "VIN is the canonical
  identifier" rule from PROJECT.md § Interaction primitives.
- **Body fields as a bulleted list** because the data is
  structured and scan-friendly. Don't use tables — markdown
  tables render unevenly across viewers.
- **Hairline rule (`---`) between alerts**, no rule before the
  first or after the last (markdown handles this naturally).
- **Use em-dashes (`—`) and middle dots (`·`)** consistently with
  the rest of the project's typographic conventions.

### How to wire it

Modify `notify.py` so that immediately after a successful POST
to Pushover (i.e., right after writing the `notifications` table
row with `success=1`), the same module also appends the alert to
`alerts/YYYY-MM-DD.md`.

Suggested implementation:

```python
def _append_alert_log(
    sent_at: datetime,
    tier: int,
    event_type: str,
    vin: str | None,
    title: str,
    body: str,
    url: str | None,
    extra_fields: dict | None = None,
) -> None:
    """Append a markdown record of this alert to alerts/YYYY-MM-DD.md."""
    log_dir = Path("alerts")
    log_dir.mkdir(exist_ok=True)
    date_str = sent_at.strftime("%Y-%m-%d")
    log_path = log_dir / f"{date_str}.md"

    # Lazy-create with a header on first alert of the day
    if not log_path.exists():
        log_path.write_text(f"# Alerts — {date_str}\n\n")

    # Format the entry...
    # (left as exercise; structure shown in "File format" above)

    with log_path.open("a") as f:
        f.write(entry)
```

`extra_fields` is for tier-specific fields like the was/now/delta
on a price drop. Keep the function signature small and pass
whatever needs to render through that dict.

### When NOT to write to the log

- **DRY_RUN mode:** if `PUSHOVER_ENABLED=false` or `DRY_RUN=true`,
  do not write to `alerts/`. The DB row already captures the
  dry-run; the markdown log should only reflect alerts that
  actually fired to Pushover.
- **Failed Pushover sends:** if the POST returned non-2xx, do
  not append to `alerts/`. The DB row captures the failure with
  `success=0`; that's the correct place. The markdown log is for
  alerts the user actually received.

This means: every entry in `alerts/*.md` corresponds 1:1 with a
notification that successfully reached the user's phone. That
property makes the log trustworthy as a "what did I actually get
alerted to" record.

### Workflow integration

The `git add . && git commit && git push` pattern in the workflow
already commits everything in the repo, including the new
`alerts/` directory. No workflow changes needed. The commit
message generated by the existing pipeline will read something
like "scrape: 1 new VIN, 1 alert fired" naturally.

If `git diff` shows changes to `data/inventory.db`,
`raw_snapshots/`, OR `alerts/`, the commit happens. If none
changed, no commit. Existing logic.

## Tests

Two unit tests, mirroring the existing notify tests:

1. `_append_alert_log` creates the file with the right header on
   first call of the day
2. Subsequent calls on the same day append (don't overwrite),
   and the file ends with a trailing rule between entries

Optionally a third: when `PUSHOVER_ENABLED=false`, no file is
created.

## Out of scope for this amendment

- A separate `digest.py` reading from `alerts/*.md` — that's
  step 8 in PROJECT.md, not now.
- Filtering or searching the log via CLI — also step 8 territory.
- Backfilling alerts that fired before this amendment shipped —
  the `notifications` DB table has them; treat the markdown log
  as starting from the first alert after this commit.
- Pruning old alert files — git history is the archive; nothing
  needs to be deleted.

## Commit hygiene

Single commit:

```
notify: append every successful alert to alerts/YYYY-MM-DD.md

Mirrors each Pushover send to a markdown log committed alongside
the rest of the run output. Provides an off-device, version-
controlled audit trail. Format follows the project's typographic
conventions (§ section markers, VIN as canonical link, em-dash
hairlines between entries).

Skip in DRY_RUN mode and on failed Pushover sends — the DB row
captures both, but the markdown log should only reflect alerts
that successfully reached the user.
```

That's it. Roughly 15-20 minutes of work. Ship and move on.
