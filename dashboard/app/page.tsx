import type { Inventory, Listing } from "./types";

// 10-min ISR: the watcher commits latest.json every ~30 min. Pulling it
// fresh every 10 min means the dashboard is at most ~10 min behind the
// last commit, never requires a Vercel rebuild on data changes.
const REVALIDATE_S = 600;

const RAW_LATEST_URL =
  "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/data/latest.json";
const RAW_DIGEST_URL =
  "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest/LATEST.md";

async function getInventory(): Promise<Inventory> {
  const res = await fetch(RAW_LATEST_URL, { next: { revalidate: REVALIDATE_S } });
  if (!res.ok) throw new Error(`Failed to fetch latest.json: ${res.status}`);
  return res.json();
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${n.toLocaleString("en-US")}`;
}

function fmtKMoney(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${(n / 1000).toFixed(1)}k`;
}

function fmtMiles(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US");
}

function fmtDistance(d: number | null): string {
  if (d == null) return "—";
  return `${Math.round(d).toLocaleString("en-US")} mi`;
}

function fmtTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toISOString().replace("T", " ").slice(0, 19) + " UTC";
}

function tierBadge(tier1Count: number, isWatchlist: boolean): boolean {
  return isWatchlist || tier1Count > 0;
}

function mbusaListingUrl(vin: string): string {
  return `https://www.mbusa.com/en/cpo/inventory/details/${vin}`;
}

function withDefaults(data: Inventory): Inventory {
  // Robust against older latest.json shapes that haven't been refreshed
  // by a post-Stage-1 watcher run yet. Median is computed from the
  // listings as a fallback, others default to zero / pass-through.
  const listings = (data.listings ?? []).map((l) => ({
    ...l,
    mbusa_listing_url: l.mbusa_listing_url ?? mbusaListingUrl(l.vin),
    is_watchlist_match: l.is_watchlist_match ?? false,
    watchlist_labels: l.watchlist_labels ?? [],
    tier1_count: l.tier1_count ?? 0,
    days_on_lot: l.days_on_lot ?? 0,
    current_price: l.current_price ?? null,
  }));
  if (data.kpis) return { ...data, listings };

  const prices = listings
    .map((l) => l.current_price)
    .filter((p): p is number => typeof p === "number" && p > 0)
    .sort((a, b) => a - b);
  const median =
    prices.length === 0
      ? null
      : prices[Math.floor(prices.length / 2)];
  return {
    ...data,
    listings,
    kpis: {
      national_pool: listings.length,
      within_criteria: listings.filter((l) => l.is_watchlist_match).length,
      median_asking: median,
      tier1_alerts_7d: 0,
    },
  };
}

export default async function Page() {
  const raw = await getInventory();
  const data = withDefaults(raw);
  const { kpis, listings } = data;

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 32 }}>
      {/* Header */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          paddingBottom: 24,
          borderBottom: "1px solid var(--fg)",
        }}
      >
        <div>
          <div className="section-marker" style={{ marginBottom: 8 }}>
            mb-wagon-watcher / 01
          </div>
          <div
            style={{
              fontSize: 28,
              fontWeight: 200,
              letterSpacing: "-0.02em",
              lineHeight: 1,
            }}
          >
            Inventory
          </div>
          <div
            style={{
              fontSize: 28,
              fontWeight: 800,
              letterSpacing: "-0.02em",
              lineHeight: 1,
              marginTop: 4,
            }}
          >
            E450 4MATIC All-Terrain
          </div>
        </div>
        <div className="metadata" style={{ textAlign: "right", lineHeight: 1.7 }}>
          <div>{fmtTimestamp(data.generated_at)}</div>
          <div>{listings.length} listings</div>
          <div>
            <a
              href={RAW_DIGEST_URL}
              className="vin-link"
              style={{ borderBottomColor: "currentColor" }}
            >
              latest digest →
            </a>
          </div>
        </div>
      </header>

      {/* KPI cards */}
      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 24,
          margin: "32px 0",
          paddingBottom: 32,
          borderBottom: "1px solid var(--rule)",
        }}
      >
        <Kpi label="National pool" value={kpis.national_pool.toString()} />
        <Kpi
          label="Within criteria"
          value={kpis.within_criteria.toString()}
          sublabel="2024+ · ≤15k mi"
        />
        <Kpi
          label="Median asking"
          value={fmtKMoney(kpis.median_asking)}
        />
        <Kpi
          label="Tier 1 alerts (7d)"
          value={kpis.tier1_alerts_7d.toString()}
          accent={kpis.tier1_alerts_7d > 0}
        />
      </section>

      {/* Section marker */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 16,
        }}
      >
        <div className="section-marker">
          § 02 — Active inventory · click VIN to view listing
        </div>
        <div className="metadata">{listings.length} listings</div>
      </div>

      {/* Inventory table */}
      <table
        className="mono"
        style={{ fontSize: 11 }}
      >
        <thead>
          <tr style={{ borderBottom: "1px solid var(--fg)" }}>
            <Th align="left">Dist</Th>
            <Th align="left">Yr</Th>
            <Th align="left">VIN</Th>
            <Th align="left">Dealer · Color</Th>
            <Th align="right">Miles</Th>
            <Th align="right">Asking</Th>
            <Th align="right">Pct</Th>
            <Th align="right">DoL</Th>
          </tr>
        </thead>
        <tbody>
          {listings.map((l) => (
            <Row key={l.vin} listing={l} />
          ))}
        </tbody>
      </table>

      {/* Footer */}
      <footer
        style={{
          marginTop: 32,
          paddingTop: 16,
          borderTop: "1px solid var(--rule)",
          display: "flex",
          justifyContent: "space-between",
          color: "#555",
          fontSize: 9,
          letterSpacing: "0.05em",
        }}
        className="mono"
      >
        <div>nafta-service.mbusa.com/api/inv/v1/en_us/used/vehicles/search</div>
        <div>
          <a
            href="https://github.com/pwysocan-droid/wagon-watcher"
            className="vin-link"
            style={{ borderBottomColor: "currentColor" }}
          >
            github.com/pwysocan-droid/wagon-watcher
          </a>
        </div>
      </footer>
    </main>
  );
}

// ---- subcomponents -------------------------------------------------------

function Kpi({
  label,
  value,
  sublabel,
  accent = false,
}: {
  label: string;
  value: string;
  sublabel?: string;
  accent?: boolean;
}) {
  const color = accent ? "var(--signal)" : "var(--fg)";
  return (
    <div>
      <div
        className="section-marker"
        style={{ marginBottom: 12, color: accent ? "var(--signal)" : "var(--muted)" }}
      >
        {label}
      </div>
      <div
        className="display"
        style={{ fontSize: 64, color }}
      >
        {value}
      </div>
      {sublabel && (
        <div className="metadata" style={{ marginTop: 6 }}>
          {sublabel}
        </div>
      )}
    </div>
  );
}

function Th({
  align,
  children,
}: {
  align: "left" | "right";
  children: React.ReactNode;
}) {
  return (
    <th
      style={{
        textAlign: align,
        padding: "10px 8px",
        fontSize: 9,
        fontWeight: 500,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        color: "var(--muted)",
      }}
    >
      {children}
    </th>
  );
}

function Row({ listing }: { listing: Listing }) {
  const flagged = tierBadge(listing.tier1_count, listing.is_watchlist_match);
  const greyed = !listing.is_watchlist_match && !flagged && (
    (listing.year ?? 0) < 2024 ||
    (listing.mileage_first_seen ?? 0) > 15000
  );
  const className = [
    "row-hover",
    flagged ? "tier1-row" : "",
    greyed ? "greyed" : "",
  ].filter(Boolean).join(" ");

  const cellStyle: React.CSSProperties = { padding: "10px 8px" };
  const colorStyle = flagged
    ? { color: "var(--signal)", fontWeight: 700 as const }
    : {};

  return (
    <tr className={className} style={{ borderBottom: "1px solid var(--rule)" }}>
      <td style={{ ...cellStyle, ...colorStyle }}>
        {fmtDistance(listing.distance_miles)}
      </td>
      <td style={cellStyle}>{listing.year ?? "—"}</td>
      <td style={cellStyle}>
        <a
          href={listing.mbusa_listing_url}
          target="_blank"
          rel="noreferrer"
          className="vin-link"
          style={colorStyle}
        >
          {listing.vin}
        </a>
        {listing.is_watchlist_match && (
          <sup style={{ fontSize: "0.7em", verticalAlign: "super", color: "var(--signal)", marginLeft: 2 }}>
            ¹
          </sup>
        )}
      </td>
      <td style={cellStyle}>
        {listing.dealer_name ?? "—"} · {listing.exterior_color ?? "—"}
      </td>
      <td style={{ ...cellStyle, textAlign: "right" }}>
        {fmtMiles(listing.mileage_first_seen)}
      </td>
      <td style={{ ...cellStyle, textAlign: "right", fontWeight: flagged ? 700 : 400 }}>
        {fmtMoney(listing.current_price)}
      </td>
      <td style={{ ...cellStyle, textAlign: "right" }}>
        {listing.fair_price_pct != null
          ? `${listing.fair_price_pct}${tierShort(listing.fair_price_tier)}`
          : "—"}
      </td>
      <td style={{ ...cellStyle, textAlign: "right" }}>
        {listing.days_on_lot}
      </td>
    </tr>
  );
}

function tierShort(t: Listing["fair_price_tier"]): string {
  if (t === "strict") return "ˢ";
  if (t === "loose") return "ˡ";
  if (t === "broad") return "ᵇ";
  return "";
}
