# mb-wagon-watcher · daily digest

**2026-10-30** · 05:00 PT snapshot

`Generated: 2026-10-30T17:43:53Z`

---

## § Population

**Population:** 29 active (no change since yesterday) · 1 watchlist match · 0 actionable

---

## § Movers

_No price moves vs. start of today (UTC)._

---

## § Floor watch

- W1KZH6AB0PB118184 — R B M of Atlanta, Inc., GA — $45,855 (down from $50,987 floor)
- W1KLH6FB6SA164745 — R B M of Atlanta, Inc., GA — $73,114 (down from $73,900 floor)
- W1KZH6AB5PB118889 — Fletcher Jones Motorc…, CA — $49,591 (down from $52,894 floor)
- W1KZH6AB4NB056172 — MB Elmbrook, WI — $52,900 (down from $54,494 floor)
- W1KLH6FB2SA159333 — MB Manhattan, NY — $79,900 (down from $81,900 floor)

_… and 7 more at floor._

---

## § Anomalies

- VIN `W1KZH6AB9NB055261` toggled status 6 times (feed instability or price-testing)
- 36 cron runs returned <30 listings (min 28) — possible API cap

---

## § Watchlist matches

- W1KLH6FB9SA152900 — MB Rochester, MN — $64,595 — DISQUALIFIED (color combo (Sonoran Brown / Macchiato Beige) — rejected 2026-10-22)

---

## § Near-miss

_Fails exactly one hard criterion, priced ≤15th pct. Surface only — criteria stand._

- `…134071` · MB Scarborough, ME · $70,571 · 4,919 mi · fails: price > $68,000 · pct 10s

---

## § Decision queue

Open decisions today:
- `…056051` · Mercedes-Benz of Edison, NJ (Ray Catena) · $74,888 · next: only if the Manhattan 2024 deal fails · paused — superseded by Manhattan 2024 (same spec/color, cleaner history, responsive dealer); email unanswered since Oct 20.
- `…053835` · Mercedes-Benz of Manhattan, NY (MBUSA factory store) · $75,900 (gone from feed) · next: Joe's response to the $67,000 offer; dealer wants to close by Oct 31 · standing offer $67,000 sent Oct 22 via Jason Rehklau (347-978-5218); fees $225 doc + $95 gas surcharge; awaiting pre-owned manager (Joe); dealer wants close by Oct 31; walk number $68,500.
- `…164745` · R B M of Atlanta, GA · $73,114 · next: mid-Nov (~day 70), or a second price cut · active; one small cut
- `…133447` · Mercedes-Benz of Georgetown, TX · $62,999 (manual) · next: only if Manhattan and Scarborough both fail · deprioritized — call only if Manhattan and Scarborough both fail.
- `…129436` · Mercedes-Benz of Youngstown, OH · $60,778 (manual) · next: only if Manhattan and Scarborough both fail · deprioritized — call only if Manhattan and Scarborough both fail.
- `(no VIN)` · Mercedes-Benz of West Covina, CA · $73,763 (manual) · next: weekly manual sweep · found off-feed 2026-10-15 (iSeeCars); VIN not yet captured
- `…084620` · Valley Imports (Porsche), Fargo, ND · $66,590 (gone from feed) · next: only if Manhattan and Scarborough both fail · deprioritized — call only if Manhattan and Scarborough both fail.

---

---

`mb-wagon-watcher · digest_daily.py · 2026-10-30T17:43:53Z`

_To annotate a VIN: edit `config/vin_annotations.json`._  
_To disqualify a VIN: edit `config/disqualified_vins.json`._  
_To track a decision: edit `config/decision_queue.json`._
