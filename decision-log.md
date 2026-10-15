# decision-log.md

Decisions made during the buying window, including the ones **not** taken,
so a later re-read doesn't relitigate a settled question. Newest entries
on top. Spec changes themselves live in criteria.md; this file records the
reasoning around them.

## 2026-10-15 — BMW sell-side: LIST on Cars & Bids, never trade in

- **Offers collected 2026-10-15:**
  - CarMax $6,000
  - Carvana $6,000
  - KBB Instant Cash Offer $8,108 (the floor)
- **Comparable sale:** a 111k-mi F31 sold on BaT for $13,000. Expectation
  at 126k mi is about $11.5–13k.
- **Decision:** the gap between instant offers and the auction market is
  about $4–5k, so by the kill criterion: **list on Cars & Bids, reserve
  about $10–10.5k.**
- **Timing:** list only **after the Mercedes is in the driveway.** Refresh
  the instant offers at sale time.
- **Never trade in.** A dealer pays about $6k for a car worth about $12k on
  the open market. This applies to every Mercedes negotiation in the
  decision queue: keep the BMW out of the deal entirely.

## 2026-10-15 — Barrington mileage exception: considered, REJECTED

- **Car:** W1KLH6FB1SA137310, MB Barrington IL, 2025, 23,212 mi.
  - Reviewed at $62,500 after 5 cuts in 41 days.
  - Cut again the same day to **$61,900** (6 cuts, −11.4% from $69,900).
  - Strict percentile 10.
- **Considered:** a mileage exception to the 15k ceiling, given the price.
- **Decision: rejected.** 23k miles is too far over the 15k ceiling,
  whatever the price. The ceiling stands for every car.
- **Not added** to `config/decision_queue.json`.
- **Why it's logged:** so November-me doesn't relitigate it when the price
  drops again. Further cuts on this car are expected and don't reopen the
  question. The digest's § Near-miss section may keep listing it; that's
  for awareness, not a prompt to act.
