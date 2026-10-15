# decision-log.md

Decisions made during the buying window, including the ones **not** taken,
so a later re-read doesn't relitigate a settled question. Newest entries
on top. Spec changes themselves live in criteria.md; this file records the
reasoning around them.

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
