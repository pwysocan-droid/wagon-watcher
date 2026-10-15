"""Survival v2 + post-fix band recheck. Writes nothing; prints the numbers
that analysis/survival_v2.md reports.

Methodology mirrors analysis/survival_v1.md:
  - first lifetime per VIN; a gone event followed by a reappearance within
    14 days is feed noise and merged; gone >14 days (or never back) is a
    "sale" dated at the gone event, at the last observed price
  - a VIN gone <=14 days before the cutoff is censored at its gone date;
    a still-listed VIN is censored at the cutoff
  - prices: price_history with price > 1000, read as-of a timestamp
  - cuts: envelope method (new running minimum), per eom_pattern.md
  - listed percentile: fairprice.py tiers/midrank, as-of first_seen against
    the pool listed at that moment

Usage: python3 analysis/survival_v2.py [path/to/inventory.db]
"""
from __future__ import annotations

import math
import sqlite3
import statistics as st
import sys
from datetime import datetime, timedelta, timezone

MERGE = timedelta(days=14)
FIX = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)       # pagination fix deployed
V1_START = datetime(2026, 4, 28, tzinfo=timezone.utc)
V1_CUTOFF = datetime(2026, 7, 31, tzinfo=timezone.utc)        # v1 ran 2026-07-30
PREFIX_CUTOFF = datetime(2026, 8, 18, 23, 59, tzinfo=timezone.utc)
V2_START = datetime(2026, 8, 20, tzinfo=timezone.utc)
TIERS = (("strict", 1, 15_000), ("loose", 2, 25_000), ("broad", 3, 40_000))
SPRING_BAND = (65_980, 67_998)


def ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load(path: str):
    db = sqlite3.connect(path)
    L = {}
    for vin, first, last, status, dealer, state, year, mi in db.execute(
        "select vin, first_seen, last_seen, status, dealer_name, dealer_state, year, "
        "mileage_first_seen from listings"
    ):
        L[vin] = dict(vin=vin, first=ts(first), last=ts(last), status=status, dealer=dealer,
                      state=state, year=year or 0, mi=mi if mi is not None else 10**9)
    H: dict[str, list] = {}
    for vin, t, p, m in db.execute(
        "select vin, observed_at, price, mileage from price_history where price > 1000 "
        "order by vin, observed_at, id"
    ):
        H.setdefault(vin, []).append((ts(t), p, m))
    E: dict[str, list] = {}
    for vin, t, kind in db.execute(
        "select vin, sent_at, event_type from notifications "
        "where event_type in ('gone','reappeared') and vin is not null order by sent_at"
    ):
        E.setdefault(vin, []).append((ts(t), kind))
    suspect = {r[0] for r in db.execute("select vin from notes where tags like '%suspect_sale%'")}
    cutoff = ts(db.execute("select max(started_at) from runs").fetchone()[0])
    return L, H, E, suspect, cutoff


def price_at(H, vin, t):
    best = None
    for when, p, _ in H.get(vin, []):
        if when <= t:
            best = p
        else:
            break
    return best if best is not None else (H[vin][0][1] if H.get(vin) else None)


def lifetime(L, E, vin, cutoff):
    """(end, sold, long_gap_reappearances) for the VIN's first lifetime, seen as of cutoff."""
    start = L[vin]["first"]
    events = [(t, k) for t, k in E.get(vin, []) if start <= t <= cutoff]
    gone_at = None
    long_gaps = 0
    for t, k in events:
        if k == "gone" and gone_at is None:
            gone_at = t
        elif k == "reappeared" and gone_at is not None:
            if t - gone_at > MERGE:
                return gone_at, True, long_gaps  # v1 semantics: sold at first long gone
            gone_at = None
    if gone_at is not None:
        if cutoff - gone_at > MERGE:
            return gone_at, True, long_gaps
        return gone_at, False, long_gaps
    return cutoff, False, long_gaps


def hindsight_reappeared(L, E, vin, sold_at, now):
    """True if a v1-style 'sale' later reappeared (dealer trade / long flap)."""
    return any(k == "reappeared" and t > sold_at for t, k in E.get(vin, []) if t <= now)


def km(rows):
    """rows: [(days, event_bool)] -> list of (t, S) and quantile helper."""
    rows = sorted(rows)
    n = len(rows)
    S, curve, i = 1.0, [], 0
    times = sorted({d for d, e in rows if e})
    for t in times:
        at_risk = sum(1 for d, _ in rows if d >= t)
        deaths = sum(1 for d, e in rows if e and d == t)
        S *= 1 - deaths / at_risk
        curve.append((t, S))
    return curve


def km_q(curve, q):
    for t, s in curve:
        if s <= 1 - q:
            return t
    return None  # not reached


def km_at(curve, day):
    s = 1.0
    for t, v in curve:
        if t <= day:
            s = v
    return s


def listed_pct(L, H, vin):
    t = L[vin]["first"] + timedelta(minutes=1)
    tgt = L[vin]
    p0 = price_at(H, vin, t)
    if p0 is None:
        return None, None
    pool = [v for v in L if L[v]["first"] <= t <= L[v]["last"] + timedelta(hours=6) and H.get(v)]
    for name, yw, mw in TIERS:
        comps = [price_at(H, v, t) for v in pool
                 if abs(L[v]["year"] - tgt["year"]) <= yw and abs(L[v]["mi"] - tgt["mi"]) <= mw]
        comps = [c for c in comps if c is not None]
        if len(comps) >= 5:
            lt = sum(c < p0 for c in comps)
            le = sum(c <= p0 for c in comps)
            return max(0, min(99, round(100 * (lt + le) / 2 / len(comps)))), name
    return None, None


def envelope_cuts(H, vin, start, end):
    pts = [(t, p) for t, p, _ in H.get(vin, []) if start <= t <= end]
    if not pts:
        return []
    cuts, run_min = [], pts[0][1]
    for t, p in pts[1:]:
        if p < run_min:
            cuts.append(((t - start).days, (run_min - p) / run_min * 100))
            run_min = p
    return cuts


def poisson_ci(k, conf=0.90):
    """Exact (Garwood) CI for a Poisson mean given k observed, via bisection."""
    a = (1 - conf) / 2

    def cdf(x, mu):
        return sum(math.exp(-mu) * mu**i / math.factorial(i) for i in range(x + 1))

    def solve(f, lo, hi):
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
        return (lo + hi) / 2

    lower = 0.0 if k == 0 else solve(lambda mu: a - (1 - cdf(k - 1, mu)), 0, 100)
    upper = solve(lambda mu: cdf(k, mu) - a, 0, 100)
    return lower, upper


def qualifying(x):
    return x["year"] >= 2024 and x["mi"] <= 15_000


def summarize(name, L, H, E, vins, cutoff):
    rows, detail = [], []
    for v in vins:
        end, sold, _ = lifetime(L, E, v, cutoff)
        days = max(0, (end - L[v]["first"]).days)
        rows.append((days, sold))
        detail.append((v, days, sold, end))
    curve = km(rows)
    sold_n = sum(e for _, e in rows)
    print(f"\n## {name}: n={len(rows)} sold={sold_n} censored={len(rows)-sold_n} "
          f"({(len(rows)-sold_n)/len(rows):.0%})")
    print(f"KM median={km_q(curve, .5)} q25={km_q(curve, .25)} q75={km_q(curve, .75)}")
    print("S(t): " + "  ".join(f"d{d}={km_at(curve, d):.2f}" for d in (1, 3, 7, 10, 14, 21, 28, 35, 43)))
    return detail, curve


def main(path):
    L, H, E, suspect, now = load(path)
    print(f"cutoff (last run) = {now:%Y-%m-%d %H:%MZ}; VINs={len(L)}; suspect_sale tags={len(suspect)}")

    v1 = [v for v in L if V1_START <= L[v]["first"] <= V1_CUTOFF and H.get(v)]
    v2 = [v for v in L if L[v]["first"] >= V2_START and H.get(v)]

    # 0. replicate v1 as v1 saw it (sanity check against survival_v1.md: n=94, 65 sold, median 15)
    summarize("v1 replication (cutoff 2026-07-31)", L, H, E, v1, V1_CUTOFF)
    d1, _ = summarize("v1 cohort, pre-fix data to 2026-08-18", L, H, E, v1, PREFIX_CUTOFF)
    v1_clean = [v for v in v1 if v not in suspect]
    summarize("v1 cohort excl suspect_sale, to 2026-08-18", L, H, E, v1_clean, PREFIX_CUTOFF)
    back = [v for v, _, s, end in d1 if s and hindsight_reappeared(L, E, v, end, now)]
    print(f"v1-cohort 'sales' that later reappeared (>14d gap, hindsight to now): {len(back)} {back}")

    # 1. v2 KM
    d2, c2 = summarize("v2 cohort (first_seen >= 2026-08-20)", L, H, E, v2, now)

    # percentile split, v2
    groups = {"<20": [], "20-50": [], ">50": [], "n/a": []}
    tiers = {}
    for v, days, sold, _ in d2:
        pct, tier = listed_pct(L, H, v)
        tiers[tier] = tiers.get(tier, 0) + 1
        g = "n/a" if pct is None else "<20" if pct < 20 else "20-50" if pct <= 50 else ">50"
        groups[g].append((days, sold))
    print("pct tiers:", tiers)
    for g, rows in groups.items():
        if rows:
            c = km(rows)
            print(f"  pct {g}: n={len(rows)} sold={sum(e for _, e in rows)} "
                  f"median={km_q(c, .5)} q25={km_q(c, .25)} q75={km_q(c, .75)}")
    # by model generation
    for label, pred in (("S214 2024+", lambda x: x["year"] >= 2024), ("S213 <=2023", lambda x: x["year"] < 2024)):
        rows = [(d, s) for v, d, s, _ in d2 if pred(L[v])]
        c = km(rows)
        print(f"  {label}: n={len(rows)} sold={sum(e for _, e in rows)} median={km_q(c, .5)} "
              f"q25={km_q(c, .25)} q75={km_q(c, .75)}")

    # envelope cuts, v2
    cuts = [c for v, _, _, end in d2 for c in envelope_cuts(H, v, L[v]["first"], end)]
    with_cut = sum(1 for v, _, _, end in d2 if envelope_cuts(H, v, L[v]["first"], end))
    if cuts:
        print(f"v2 envelope cuts: {len(cuts)} cuts on {with_cut}/{len(d2)} VINs; "
              f"mean {st.mean(c for _, c in cuts):.2f}%; first-cut median day "
              f"{st.median(min(envelope_cuts(H, v, L[v]['first'], e))[0] for v, _, _, e in d2 if envelope_cuts(H, v, L[v]['first'], e))}")
        for lo, hi in ((0, 14), (15, 24), (25, 35), (36, 999)):
            b = [c for d, c in cuts if lo <= d <= hi]
            print(f"  DoL {lo}-{hi}: n={len(b)} mean={st.mean(b) if b else 0:.2f}%")

    # 2. exposure-matched tempo
    print("\n## tempo: share gone (sold) within 14 / 21 days, VINs with >=21d exposure + 14d confirmation")
    def tempo(label, vins, cutoff):
        elig = [v for v in vins if L[v]["first"] + timedelta(days=35) <= cutoff]
        res = []
        for v in elig:
            end, sold, _ = lifetime(L, E, v, cutoff)
            d = (end - L[v]["first"]).days
            res.append((sold and d <= 14, sold and d <= 21))
        n = len(res)
        a, b = sum(r[0] for r in res), sum(r[1] for r in res)
        print(f"  {label}: n={n}  <=14d {a} ({a/n:.0%})  <=21d {b} ({b/n:.0%})")
    tempo("(a) v1 excl suspect_sale", v1_clean, PREFIX_CUTOFF)
    tempo("(b) v1 incl suspect_sale", v1, PREFIX_CUTOFF)
    tempo("(c) v2", v2, now)
    tempo("(c') v2, S214 2024+ only", [v for v in v2 if L[v]["year"] >= 2024], now)
    tempo("(a') v1 excl suspect, S214 2024+ only", [v for v in v1_clean if L[v]["year"] >= 2024], PREFIX_CUTOFF)

    # 3. clearing band, post-fix
    print("\n## qualifying completed lifetimes with sale date >= fix (any first_seen)")
    for v, x in sorted(L.items(), key=lambda kv: kv[1]["first"]):
        if not qualifying(x) or not H.get(v):
            continue
        end, sold, _ = lifetime(L, E, v, now)
        if sold and end >= FIX:
            hs = [p for t, p, _ in H[v] if t <= end]
            print(f"  {v} {x['year']} {x['mi']:,}mi {x['dealer']}, {x['state']} first {x['first']:%m-%d} "
                  f"sold {end:%m-%d} ({(end-x['first']).days}d) list {hs[0]:,} final {hs[-1]:,} "
                  f"{'IN band' if SPRING_BAND[0] <= hs[-1] <= SPRING_BAND[1] else 'below' if hs[-1] < SPRING_BAND[0] else 'above'}"
                  f"{' [v2 cohort]' if x['first'] >= V2_START else ''}")

    # 4. qualifying inflow at the shipping-adjusted $67k cap
    print("\n## qualifying listings that ever asked <= $67,000, by first_seen month")
    months = {}
    for v, x in L.items():
        if qualifying(x) and H.get(v) and min(p for _, p, _ in H[v]) <= 67_000:
            months.setdefault(x["first"].strftime("%Y-%m"), []).append(
                (v, x["first"], min(p for _, p, _ in H[v]), x["dealer"]))
    for m in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"):
        items = months.get(m, [])
        print(f"  {m}: {len(items)}  " + "; ".join(
            f"{d} {lo:,} ({'post' if f >= FIX else 'pre'}{', baseline' if f < V1_START else ''})"
            for _, f, lo, d in items))
    for label, a, b in (("post-fix", FIX, now), ("pre-fix Apr28-Aug18", V1_START, PREFIX_CUTOFF),
                        ("all non-baseline", V1_START, now)):
        k = sum(1 for items in months.values() for _, f, _, _ in items if a <= f <= b)
        days = (b - a).total_seconds() / 86400
        lo, hi = poisson_ci(k)
        scale = 46 / days
        mu = k * scale
        print(f"  {label}: k={k} over {days:.0f}d -> expected Oct15-Nov30 (46d) {mu:.2f} "
              f"[90% CI {lo*scale:.2f}-{hi*scale:.2f}]  P(0)={math.exp(-mu):.0%}  P(>=2)={1-math.exp(-mu)*(1+mu):.0%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/inventory.db")
