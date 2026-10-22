# mb-wagon-watcher · daily digest

**2026-10-22** · 05:00 PT snapshot

`Generated: 2026-10-22T16:40:00Z`

---

## § Population

**Population:** 32 active (-6 net since yesterday) · 1 watchlist match · 1 actionable

---

## § Movers

- W1KZH6AB7PB116786 — MB Hilton Head, SC — $60,084 (-$3,500 / -5.50%)

---

## § Floor watch

- W1KZH6AB0PB118184 — R B M of Atlanta, Inc., GA — $46,428 (down from $50,987 floor)
- W1KLH6FB6SA164745 — R B M of Atlanta, Inc., GA — $73,114 (down from $73,900 floor)
- W1KZH6AB5PB118889 — Fletcher Jones Motorc…, CA — $50,892 (down from $52,894 floor)
- W1KZH6AB4NB056172 — MB Elmbrook, WI — $52,900 (down from $54,494 floor)
- W1KZH6AB7PB116786 — MB Hilton Head, SC — $60,084 (down from $65,584 floor)

_… and 8 more at floor._

---

## § Anomalies

- VIN `W1KLH6FB0SA155958` toggled status 13 times (feed instability or price-testing)
- VIN `W1KLH6FB1RA026170` toggled status 14 times (feed instability or price-testing)
- VIN `W1KLH6FB1SA137310` toggled status 3 times (feed instability or price-testing)
- VIN `W1KLH6FB2SA159333` toggled status 15 times (feed instability or price-testing)
- VIN `W1KLH6FB2TA196545` toggled status 16 times (feed instability or price-testing)
- VIN `W1KLH6FB4RA056120` toggled status 15 times (feed instability or price-testing)
- VIN `W1KLH6FB5RA026219` toggled status 13 times (feed instability or price-testing)
- VIN `W1KLH6FB5SA134071` toggled status 16 times (feed instability or price-testing)
- VIN `W1KLH6FB6RA026262` toggled status 15 times (feed instability or price-testing)
- VIN `W1KLH6FB6SA164745` toggled status 4 times (feed instability or price-testing)
- VIN `W1KLH6FB8SA101288` toggled status 3 times (feed instability or price-testing)
- VIN `W1KLH6FB8TA197277` toggled status 15 times (feed instability or price-testing)
- VIN `W1KLH6FB9SA151505` toggled status 4 times (feed instability or price-testing)
- VIN `W1KLH6FB9SA152900` toggled status 13 times (feed instability or price-testing)
- VIN `W1KLH6FB9SA163752` toggled status 18 times (feed instability or price-testing)
- VIN `W1KLH6FBXRA026247` toggled status 15 times (feed instability or price-testing)
- VIN `W1KZH6AB0PB118184` toggled status 4 times (feed instability or price-testing)
- VIN `W1KZH6AB3PB111794` toggled status 15 times (feed instability or price-testing)
- VIN `W1KZH6AB4NB056172` toggled status 13 times (feed instability or price-testing)
- VIN `W1KZH6AB5PB149060` toggled status 4 times (feed instability or price-testing)
- VIN `W1KZH6AB5PB178834` toggled status 4 times (feed instability or price-testing)
- VIN `W1KZH6AB6PB147527` toggled status 15 times (feed instability or price-testing)
- VIN `W1KZH6AB7PB116786` toggled status 15 times (feed instability or price-testing)
- VIN `W1KZH6ABXPB101554` toggled status 15 times (feed instability or price-testing)
- 17 cron runs returned <30 listings (min 21) — possible API cap
- New dealer first-seen: Mercedes-Benz of West Chester
- New dealer first-seen: Mercedes-Benz of Goldens Bridge

---

## § Watchlist matches

- W1KLH6FB9SA152900 — MB Rochester, MN — $65,095

---

## § Near-miss

_Fails exactly one hard criterion, priced ≤15th pct. Surface only — criteria stand._

- `…155958` · Park Place Motorcars …, TX · $70,577 · 5,343 mi · fails: price > $68,000 · pct 15s

---

## § Decision queue

Open decisions today:
- `…056051` · Mercedes-Benz of Edison, NJ (Ray Catena) · $75,225 · next: dealer's written itemized out-the-door quote + in-service date; then within 48h of the next lot sweep (every 4-10 days) · active; cap exception granted 2026-10-19 — best spec; strategy: negotiate now, not wait (dealer cuts unlikely to reach walk number)
- `…114903` · Mercedes-Benz of Hoffman Estates, IL · $68,999 (gone from feed) · next: dealer call result (same day) · vanished from consumer surfaces 2026-10-15, feed still active; dealer call pending
- `…212378` · Mercedes-Benz of Los Angeles, CA (Lithia) · $75,081 · next: within 48h of the first CarGurus batch cut on this VIN (check every 2-3 days from Oct 29) · active; no real cut (price flips between $74,900 and $75,081 as fees are shown or hidden)
- `…163752` · Mercedes-Benz of Manhattan, NY · $72,400 (gone from feed) · next: day-45 mark ~Nov 8, or any price cut before then · active; uncut since listing Sep 24
- `…164745` · R B M of Atlanta, GA · $73,114 · next: mid-Nov (~day 70), or a second price cut · active; one small cut
- `…133447` · Mercedes-Benz of Georgetown, TX · $62,999 (manual) · next: first call · found off-feed 2026-10-15; not called
- `…129436` · Mercedes-Benz of Youngstown, OH · $60,778 (manual) · next: first call · found off-feed 2026-10-15; not called
- `(no VIN)` · Mercedes-Benz of West Covina, CA · $73,763 (manual) · next: weekly manual sweep · found off-feed 2026-10-15 (iSeeCars); VIN not yet captured
- `…084620` · Valley Imports (Porsche), Fargo, ND · $66,590 (gone from feed) · next: first call · feed scored it sold 2026-09-24, but Cars.com still lists it as Manufacturer CPO at $66,590; availability unconfirmed

---

---

`mb-wagon-watcher · digest_daily.py · 2026-10-22T16:40:00Z`

_To annotate a VIN: edit `config/vin_annotations.json`._  
_To disqualify a VIN: edit `config/disqualified_vins.json`._  
_To track a decision: edit `config/decision_queue.json`._
