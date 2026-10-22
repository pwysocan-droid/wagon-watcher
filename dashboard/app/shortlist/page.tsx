import type { Listing } from "../types";

// Shortlist: every live car that is non-white with ≤10k miles (rule lives in
// config/shortlist.json), plus pinned VINs, with price history, dealer
// behavior notes and a link to the car on the DEALER's own site. MBUSA
// detail links are unreliable, so they're never used here.
//
// Same 10-min ISR and raw-GitHub sources as the main page, so new cars and
// price changes appear without a redeploy.
export const revalidate = 600;

const RAW = "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main";

interface Observation { observed_at: string; price: number; mileage: number }
interface HistoryVin {
  year: number | null;
  dealer: string | null;
  first_seen_at: string;
  current_price: number | null;
  current_mileage: number | null;
  status: string;
  observations: Observation[];
}
interface ShortlistConfig {
  rule?: { max_miles?: number; exclude_color_contains?: string[] };
  pinned?: string[];
  excluded?: Record<string, string>;
  cars?: Record<string, {
    dealer_listing_url?: string;
    url_kind?: "dealer_vdp" | "dealer_search" | "cars_com" | string;
    verified?: boolean;
    stock?: string;
    notes?: string;
    flags?: string;
    fees_note?: string;
    car_price_history?: string;
  }>;
  dealers?: Record<string, { group?: string; behavior?: string }>;
}

async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${RAW}/${path}`, { next: { revalidate } });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

// ---- price-series cleanup ------------------------------------------------

// The feed flips some cars between two prices for days (e.g. Edison
// $73,995 ↔ $75,225 as the doc fee is shown or hidden). Treat a price that
// returns to the immediately-previous level as a flap, and keep only real
// steps: each kept point is a price the car moved to and stayed at.
interface Step { at: string; price: number }

function cleanSteps(obs: Observation[]): { steps: Step[]; flapPair: [number, number] | null } {
  const raw = obs.filter((o) => o.price > 1000);
  const steps: Step[] = [];
  let flapCount = 0;
  let pair: [number, number] | null = null;
  for (const o of raw) {
    const last = steps[steps.length - 1];
    if (last && last.price === o.price) continue;
    const prev = steps[steps.length - 2];
    if (prev && prev.price === o.price) {
      // A→B→A: drop the B, count the flap.
      flapCount++;
      pair = [Math.min(prev.price, last.price), Math.max(prev.price, last.price)];
      steps.pop();
      continue;
    }
    steps.push({ at: o.observed_at, price: o.price });
  }
  return { steps, flapPair: flapCount >= 2 ? pair : null };
}

function daysBetween(a: string, b: Date): number {
  return Math.max(0, Math.floor((b.getTime() - new Date(a).getTime()) / 86_400_000));
}

const money = (n: number | null | undefined) => (n == null ? "—" : `$${n.toLocaleString("en-US")}`);
const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

// ---- page ----------------------------------------------------------------

interface Row {
  vin: string;
  year: number | null;
  dealer: string;
  state: string | null;
  color: string;
  interior: string;
  miles: number | null;
  price: number | null;
  pct: number | null;
  firstSeen: string;
  status: "active" | "gone";
  dealerSite: string | null;
  steps: Step[];
  flapPair: [number, number] | null;
}

export default async function Shortlist() {
  const [latest, history, config] = await Promise.all([
    getJson<{ generated_at: string; listings: Listing[] }>("data/latest.json", { generated_at: "", listings: [] }),
    getJson<{ vins: Record<string, HistoryVin> }>("data/price_history.json", { vins: {} }),
    getJson<ShortlistConfig>("config/shortlist.json", {}),
  ]);

  const maxMiles = config.rule?.max_miles ?? 10_000;
  const badColors = (config.rule?.exclude_color_contains ?? ["white"]).map((c) => c.toLowerCase());
  const excluded = config.excluded ?? {};
  const now = new Date();

  const matches = (l: Listing) =>
    (l.mileage_first_seen ?? Infinity) <= maxMiles &&
    !badColors.some((c) => (l.exterior_color ?? "").toLowerCase().includes(c));

  const live = new Map(latest.listings.map((l) => [l.vin, l]));
  const vins = new Set<string>([
    ...latest.listings.filter(matches).map((l) => l.vin),
    ...(config.pinned ?? []),
  ]);

  const rows: Row[] = [...vins]
    .filter((v) => !(v in excluded))
    .map((vin): Row => {
      const l = live.get(vin);
      const h = history.vins[vin];
      const { steps, flapPair } = cleanSteps(h?.observations ?? []);
      return {
        vin,
        year: l?.year ?? h?.year ?? null,
        dealer: l?.dealer_name ?? h?.dealer ?? "—",
        state: l?.dealer_state ?? null,
        color: l?.exterior_color ?? "—",
        interior: l?.interior_color ?? "—",
        miles: l?.mileage_first_seen ?? h?.current_mileage ?? null,
        price: flapPair ? flapPair[0] : (l?.current_price ?? h?.current_price ?? null),
        pct: l?.fair_price_pct ?? null,
        firstSeen: l?.first_seen ?? h?.first_seen_at ?? now.toISOString(),
        status: l ? "active" : "gone",
        dealerSite: l?.dealer_site_url ?? null,
        steps,
        flapPair,
      };
    })
    .sort((a, b) => (a.status === b.status ? (a.price ?? 9e9) - (b.price ?? 9e9) : a.status === "active" ? -1 : 1));

  const active = rows.filter((r) => r.status === "active");
  const gone = rows.filter((r) => r.status === "gone");

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 16px" }}>
      <header style={{ paddingBottom: 24, borderBottom: "1px solid var(--fg)", display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div>
          <div className="section-marker" style={{ marginBottom: 8 }}>mb-wagon-watcher / shortlist</div>
          <div style={{ fontSize: 28, fontWeight: 200, letterSpacing: "-0.02em", lineHeight: 1 }}>Shortlist</div>
          <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1, marginTop: 4 }}>
            Not white · ≤{maxMiles.toLocaleString("en-US")} mi
          </div>
        </div>
        <div className="metadata" style={{ textAlign: "right", lineHeight: 1.7 }}>
          {latest.generated_at && <div>feed {latest.generated_at.replace("T", " ").slice(0, 16)} UTC</div>}
          <div>{active.length} live · {gone.length} gone</div>
          <div><a href="/" className="vin-link" style={{ borderBottomColor: "currentColor" }}>← all inventory</a></div>
        </div>
      </header>

      <Section title={`§ 01 — Live · ${active.length}`}>
        {active.map((r) => <Card key={r.vin} row={r} config={config} now={now} />)}
      </Section>

      {gone.length > 0 && (
        <Section title={`§ 02 — Gone from feed · ${gone.length}`}>
          {gone.map((r) => <Card key={r.vin} row={r} config={config} now={now} />)}
        </Section>
      )}

      {Object.keys(excluded).length > 0 && (
        <div className="metadata" style={{ marginTop: 32, paddingTop: 16, borderTop: "1px solid var(--rule)" }}>
          Excluded: {Object.entries(excluded).map(([v, why]) => `…${v.slice(-6)} (${why})`).join(" · ")}
        </div>
      )}
    </main>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginTop: 32 }}>
      <div className="section-marker" style={{ marginBottom: 16 }}>{title}</div>
      <div style={{ display: "grid", gap: 16 }}>{children}</div>
    </section>
  );
}

function Card({ row, config, now }: { row: Row; config: ShortlistConfig; now: Date }) {
  const car = config.cars?.[row.vin] ?? {};
  const dealer = config.dealers?.[row.dealer] ?? {};
  const first = row.steps[0]?.price ?? null;
  const delta = first != null && row.price != null ? row.price - first : null;
  const cuts = row.steps.slice(1).filter((s, i) => s.price < row.steps[i].price).length;
  const gone = row.status === "gone";

  const link = car.dealer_listing_url ?? row.dealerSite;
  const linkLabel = car.dealer_listing_url
    ? car.url_kind === "cars_com" ? "Listing on Cars.com →"
      : car.url_kind === "dealer_search" ? "Dealer site search →"
      : "Dealer listing →"
    : "Dealer site (search VIN) →";

  return (
    <article
      className="mono shortlist-card"
      style={{ opacity: gone ? 0.6 : 1 }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 700, fontFamily: "var(--font-sans)" }}>
          {row.year ?? "—"} · {row.dealer}{row.state ? `, ${row.state}` : ""}
        </div>
        <div className="metadata" style={{ marginTop: 4 }}>
          {row.color} / {row.interior} · {row.miles != null ? `${row.miles.toLocaleString("en-US")} mi` : "—"}
        </div>
        <div style={{ display: "flex", gap: 24, marginTop: 12, alignItems: "baseline", flexWrap: "wrap" }}>
          <div className="display" style={{ fontSize: 32, color: gone ? "var(--muted)" : "var(--fg)" }}>{money(row.price)}</div>
          <div style={{ color: delta != null && delta < 0 ? "var(--signal)" : "var(--muted)" }}>
            {delta == null || delta === 0 ? "no change" : `${delta < 0 ? "−" : "+"}${money(Math.abs(delta))} since listed`}
          </div>
          <div className="metadata">
            {cuts} cut{cuts === 1 ? "" : "s"} · day {daysBetween(row.firstSeen, now)}
            {row.pct != null ? ` · pct ${row.pct}` : ""}
            {gone ? " · GONE" : ""}
          </div>
        </div>
        {row.flapPair && (
          <div className="metadata" style={{ marginTop: 6 }}>
            Feed flips {money(row.flapPair[0])} ↔ {money(row.flapPair[1])} (fees shown/hidden); lower shown.
          </div>
        )}
        <Sparkline steps={row.steps} now={now} />
        <div className="metadata" style={{ marginTop: 6, lineHeight: 1.6 }}>
          {row.steps.map((s, i) => (
            <span key={s.at}>
              {i > 0 && " → "}
              {shortDate(s.at)} {money(s.price)}
            </span>
          ))}
        </div>
      </div>

      <div style={{ minWidth: 0, lineHeight: 1.6 }}>
        {link ? (
          <a href={link} target="_blank" rel="noreferrer" className="vin-link" style={{ fontWeight: 700, color: "var(--signal)" }}>
            {linkLabel}
          </a>
        ) : (
          <span className="metadata">No dealer link yet</span>
        )}
        <div className="metadata" style={{ marginTop: 2 }}>
          {row.vin}{car.stock ? ` · stock ${car.stock}` : ""}
        </div>
        {(dealer.group || dealer.behavior) && (
          <p style={{ margin: "12px 0 0" }}>
            <span className="section-marker">Dealer</span>{" "}
            {dealer.group && <strong>{dealer.group}. </strong>}
            {dealer.behavior}
          </p>
        )}
        {car.car_price_history && (
          <p style={{ margin: "8px 0 0" }}><span className="section-marker">Price history (dealer side)</span> {car.car_price_history}</p>
        )}
        {car.fees_note && <p style={{ margin: "8px 0 0" }}><span className="section-marker">Fees</span> {car.fees_note}</p>}
        {car.flags && <p style={{ margin: "8px 0 0", color: "var(--signal)" }}><span className="section-marker">Flags</span> {car.flags}</p>}
        {car.notes && <p style={{ margin: "8px 0 0" }}><span className="section-marker">Notes</span> {car.notes}</p>}
      </div>
    </article>
  );
}

// Step chart of real price levels from first sighting to now.
function Sparkline({ steps, now }: { steps: Step[]; now: Date }) {
  if (steps.length === 0) return null;
  const W = 320, H = 44, P = 4;
  const t0 = new Date(steps[0].at).getTime();
  const t1 = Math.max(now.getTime(), t0 + 86_400_000);
  const prices = steps.map((s) => s.price);
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const x = (t: number) => P + ((t - t0) / (t1 - t0)) * (W - 2 * P);
  const y = (p: number) => (hi === lo ? H / 2 : P + ((hi - p) / (hi - lo)) * (H - 2 * P));
  let d = "";
  steps.forEach((s, i) => {
    const xi = x(new Date(s.at).getTime());
    d += i === 0 ? `M${xi},${y(s.price)}` : `H${xi}V${y(s.price)}`;
  });
  d += `H${x(t1)}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ marginTop: 12, maxWidth: W, display: "block" }} aria-label="price history">
      <path d={d} fill="none" stroke="var(--fg)" strokeWidth={1.5} />
      {steps.slice(1).map((s, i) =>
        s.price < steps[i].price ? (
          <circle key={s.at} cx={x(new Date(s.at).getTime())} cy={y(s.price)} r={2.5} fill="var(--signal)" />
        ) : null,
      )}
    </svg>
  );
}
