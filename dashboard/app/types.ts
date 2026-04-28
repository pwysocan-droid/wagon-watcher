// Shape of data/latest.json as written by run.write_latest_json().
// Source of truth for the schema lives in run.py — keep this file in sync
// when run.py's payload structure changes.

export interface Listing {
  vin: string;
  year: number | null;
  model: string | null;
  trim: string | null;
  body_style: string | null;
  exterior_color: string | null;
  interior_color: string | null;
  dealer_name: string | null;
  dealer_state: string | null;
  dealer_zip: string | null;
  distance_miles: number | null;
  mileage_first_seen: number | null;
  photo_url: string | null;
  listing_url: string | null;
  status: "active" | "reappeared" | string;
  first_seen: string;
  last_seen: string;
  fair_price_pct: number | null;
  fair_price_tier: "strict" | "loose" | "broad" | null;
  dealer_site_price: number | null;
  dealer_site_url: string | null;
  current_price: number | null;
  tier1_count: number;
  is_watchlist_match: boolean;
  watchlist_labels: string[];
  days_on_lot: number;
  mbusa_listing_url: string;
}

export interface KPIs {
  national_pool: number;
  within_criteria: number;
  median_asking: number | null;
  tier1_alerts_7d: number;
}

export interface Inventory {
  generated_at: string;
  count: number;
  kpis: KPIs;
  listings: Listing[];
}
