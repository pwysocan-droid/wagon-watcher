import { NextResponse } from "next/server";

// Single-call agent onboarding: returns the manifest plus the full
// markdown content of the latest daily and latest weekly digests.
// An agent that hits this endpoint once has everything it needs to
// orient: what's available, and what's most recent.

const RAW_BASE =
  "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest";
const FETCH_REVALIDATE_S = 600;

type ManifestItem = {
  label: string;
  href: string;
  api_url: string;
  size_bytes: number;
};

type RawManifest = {
  generated_at: string;
  weekly: ManifestItem[];
  daily: ManifestItem[];
};

function withCors(res: NextResponse): NextResponse {
  res.headers.set("Access-Control-Allow-Origin", "*");
  res.headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  return res;
}

async function fetchText(url: string): Promise<string | null> {
  const res = await fetch(url, { next: { revalidate: FETCH_REVALIDATE_S } });
  if (!res.ok) return null;
  return res.text();
}

export async function OPTIONS() {
  return withCors(new NextResponse(null, { status: 204 }));
}

export async function GET() {
  const manifestText = await fetchText(`${RAW_BASE}/index.json`);
  if (!manifestText) {
    return withCors(
      NextResponse.json(
        { error: "Manifest fetch failed" },
        { status: 502 },
      ),
    );
  }
  const manifest = JSON.parse(manifestText) as RawManifest;

  const latestDailyItem = manifest.daily[0] ?? null;
  const latestWeeklyItem = manifest.weekly[0] ?? null;

  // Fetch both in parallel; null when the manifest section is empty.
  const [latestDailyContent, latestWeeklyContent] = await Promise.all([
    latestDailyItem
      ? fetchText(`${RAW_BASE}/daily/${latestDailyItem.label}.md`)
      : Promise.resolve(null),
    latestWeeklyItem
      ? fetchText(`${RAW_BASE}/weekly/${latestWeeklyItem.label}.md`)
      : Promise.resolve(null),
  ]);

  return withCors(
    NextResponse.json({
      manifest: {
        generated_at: manifest.generated_at,
        total_count: manifest.weekly.length + manifest.daily.length,
        weekly: manifest.weekly,
        daily: manifest.daily,
      },
      latest_daily: latestDailyItem && latestDailyContent !== null
        ? { label: latestDailyItem.label, content: latestDailyContent }
        : null,
      latest_weekly: latestWeeklyItem && latestWeeklyContent !== null
        ? { label: latestWeeklyItem.label, content: latestWeeklyContent }
        : null,
    }),
  );
}
