# mb-wagon-watcher · daily digest

**2026-10-20** · 05:00 PT snapshot

`Generated: 2026-10-20T16:23:04Z`

---

## § Population

**Population:** 25 active (-6 net since yesterday) · 0 watchlist matches · 0 actionable

---

## § Movers

_No price moves vs. start of today (UTC)._

---

## § Floor watch

- W1KZH6AB0PB118184 — R B M of Atlanta, Inc., GA — $46,428 (down from $50,987 floor)
- W1KLH6FB1SA114903 — MB Hoffman Estates, IL — $68,999 (down from $73,998 floor)
- W1KLH6FB0RA056051 — MB Edison, NJ — $73,995 (down from $74,997 floor)
- W1KLH6FB1SA137310 — MB Barrington, IL — $61,900 (down from $69,900 floor)
- W1KLH6FB6SA164745 — R B M of Atlanta, Inc., GA — $73,114 (down from $73,900 floor)

_… and 5 more at floor._

---

## § Anomalies

- VIN `W1KLH6FB6RA026133` toggled status 21 times (feed instability or price-testing)
- VIN `W1KLH6FB8TA197277` toggled status 21 times (feed instability or price-testing)
- VIN `W1KZH6AB3PB111794` toggled status 30 times (feed instability or price-testing)
- VIN `W1KZH6AB7PB116786` toggled status 21 times (feed instability or price-testing)
- 26 cron runs returned <30 listings (min 25) — possible API cap

---

## § Watchlist matches

_No active watchlist matches._

---

## § Near-miss

_Fails exactly one hard criterion, priced ≤15th pct. Surface only — criteria stand._

- `…137310` · MB Barrington, IL · $61,900 · 23,197 mi · fails: miles > 15,000 · pct 8s

---

## § Decision queue

Open decisions today:
- `…056051` · Mercedes-Benz of Edison, NJ (Ray Catena) · $73,995 · next: dealer's written itemized out-the-door quote + in-service date; then within 48h of the next lot sweep (every 4-10 days) · active; cap exception granted 2026-10-19 — best spec; strategy: negotiate now, not wait (dealer cuts unlikely to reach walk number)
- `…114903` · Mercedes-Benz of Hoffman Estates, IL · $68,999 · next: dealer call result (same day) · vanished from consumer surfaces 2026-10-15, feed still active; dealer call pending
- `…212378` · Mercedes-Benz of Los Angeles, CA (Lithia) · $74,900 · next: within 48h of the first CarGurus batch cut on this VIN (check every 2-3 days from Oct 29) · active; no real cut (price flips between $74,900 and $75,081 as fees are shown or hidden)
- `…163752` · Mercedes-Benz of Manhattan, NY · $72,900 · next: day-45 mark ~Nov 8, or any price cut before then · active; uncut since listing Sep 24
- `…164745` · R B M of Atlanta, GA · $73,114 · next: mid-Nov (~day 70), or a second price cut · active; one small cut
- `…133447` · Mercedes-Benz of Georgetown, TX · $62,999 (manual) · next: first call · found off-feed 2026-10-15; not called
- `…129436` · Mercedes-Benz of Youngstown, OH · $60,778 (manual) · next: first call · found off-feed 2026-10-15; not called
- `(no VIN)` · Mercedes-Benz of West Covina, CA · $73,763 (manual) · next: weekly manual sweep · found off-feed 2026-10-15 (iSeeCars); VIN not yet captured
- `…084620` · Valley Imports (Porsche), Fargo, ND · $66,590 (gone from feed) · next: first call · feed scored it sold 2026-09-24, but Cars.com still lists it as Manufacturer CPO at $66,590; availability unconfirmed

---

---

`mb-wagon-watcher · digest_daily.py · 2026-10-20T16:23:04Z`

_To annotate a VIN: edit `config/vin_annotations.json`._  
_To disqualify a VIN: edit `config/disqualified_vins.json`._  
_To track a decision: edit `config/decision_queue.json`._
