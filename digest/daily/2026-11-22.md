# mb-wagon-watcher · daily digest

**2026-11-22** · 05:00 PT snapshot

`Generated: 2026-11-22T19:13:24Z`

---

## § Population

**Population:** 31 active (-4 net since yesterday) · 1 watchlist match · 1 actionable

---

## § Movers

_No price moves vs. start of today (UTC)._

---

## § Floor watch

- W1KZH6AB0PB118184 — R B M of Atlanta, Inc., GA — $45,276 (down from $50,987 floor)
- W1KLH6FB9SA151505 — R B M of Alpharetta, GA — $73,797 (down from $78,939 floor)
- W1KZH6AB4NB056172 — MB Elmbrook, WI — $51,380 (down from $54,494 floor)
- WDDZH6JB3LA707763 — MB Columbus, GA — $43,390 (down from $43,690 floor)
- W1KLH6FB3RA026199 — MB El Cajon, CA — $77,621 (down from $82,121 floor)

_… and 7 more at floor._

---

## § Anomalies

- VIN `W1KZH6ABXPB183379` toggled status 3 times (feed instability or price-testing)
- 2 cron runs returned <30 listings (min 29) — possible API cap

---

## § Watchlist matches

- W1KLH6FB5SA129436 — MB Richmond, VA — $66,974

---

## § Near-miss

_Fails exactly one hard criterion, priced ≤15th pct. Surface only — criteria stand._

- `…083959` · MB Farmington, UT · $62,951 · 28,662 mi · fails: miles > 15,000 · pct 8s
- `…136418` · MB West Covina, CA · $69,885 · 7,920 mi · fails: price > $68,000 · pct 11s

---

## § Decision queue

Open decisions today:
- `…056051` · Mercedes-Benz of Edison, NJ (Ray Catena) · $74,888 (gone from feed) · next: only if the Manhattan 2024 deal fails · paused — superseded by Manhattan 2024 (same spec/color, cleaner history, responsive dealer); email unanswered since Oct 20.
- `…164745` · R B M of Atlanta, GA · $73,114 (gone from feed) · next: mid-Nov (~day 70), or a second price cut · active; one small cut
- `…133447` · Mercedes-Benz of Georgetown, TX · $62,999 (manual) · next: only if Manhattan and Scarborough both fail · deprioritized — call only if Manhattan and Scarborough both fail.
- `…129436` · Mercedes-Benz of Youngstown, OH · $66,974 (manual) · next: only if Manhattan and Scarborough both fail · deprioritized — call only if Manhattan and Scarborough both fail.
- `(no VIN)` · Mercedes-Benz of West Covina, CA · $73,763 (manual) · next: weekly manual sweep · found off-feed 2026-10-15 (iSeeCars); VIN not yet captured
- `…084620` · Valley Imports (Porsche), Fargo, ND · $66,590 (gone from feed) · next: only if Manhattan and Scarborough both fail · deprioritized — call only if Manhattan and Scarborough both fail.

---

---

`mb-wagon-watcher · digest_daily.py · 2026-11-22T19:13:24Z`

_To annotate a VIN: edit `config/vin_annotations.json`._  
_To disqualify a VIN: edit `config/disqualified_vins.json`._  
_To track a decision: edit `config/decision_queue.json`._
