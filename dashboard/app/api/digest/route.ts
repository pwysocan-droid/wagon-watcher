import { NextResponse } from "next/server";

// Server-side fetch goes straight to raw GH (no CORS concerns server-side,
// no need to round-trip through the dashboard's own /digest rewrite).
const RAW_BASE =
  "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest";
const PUBLIC_BASE = "https://wagon-watcher.vercel.app/digest";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const WEEK_RE = /^\d{4}-W\d{2}$/;
const MAX_RANGE_DAYS = 90;
const FETCH_REVALIDATE_S = 600;

type Kind = "daily" | "weekly";

function isValidDate(s: string): boolean {
  if (!DATE_RE.test(s)) return false;
  const d = new Date(`${s}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

function isValidWeek(s: string): boolean {
  if (!WEEK_RE.test(s)) return false;
  const w = Number(s.slice(6));
  return w >= 1 && w <= 53;
}

function withCors(res: NextResponse): NextResponse {
  res.headers.set("Access-Control-Allow-Origin", "*");
  res.headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  return res;
}

function badRequest(msg: string): NextResponse {
  return withCors(NextResponse.json({ error: msg }, { status: 400 }));
}

async function fetchDigest(kind: Kind, label: string) {
  const url = `${RAW_BASE}/${kind}/${label}.md`;
  const res = await fetch(url, { next: { revalidate: FETCH_REVALIDATE_S } });
  if (!res.ok) return null;
  const content = await res.text();
  return {
    label,
    url: `${PUBLIC_BASE}/${kind}/${label}.md`,
    size_bytes: new TextEncoder().encode(content).length,
    content,
  };
}

function enumerateDates(start: string, end: string): string[] {
  const out: string[] = [];
  const e = new Date(`${end}T00:00:00Z`).getTime();
  for (
    let t = new Date(`${start}T00:00:00Z`).getTime();
    t <= e;
    t += 86_400_000
  ) {
    out.push(new Date(t).toISOString().slice(0, 10));
  }
  return out;
}

export async function OPTIONS() {
  return withCors(new NextResponse(null, { status: 204 }));
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const date = searchParams.get("date");
  const week = searchParams.get("week");
  const start = searchParams.get("start");
  const end = searchParams.get("end");

  // Mutual exclusion across the three input modes.
  const modes = [
    date != null,
    week != null,
    start != null || end != null,
  ].filter(Boolean).length;
  if (modes === 0) {
    return badRequest(
      "Provide ?date=YYYY-MM-DD, ?week=YYYY-Www, or ?start=YYYY-MM-DD&end=YYYY-MM-DD",
    );
  }
  if (modes > 1) {
    return badRequest("Use only one of: date, week, or (start + end)");
  }

  if (date) {
    if (!isValidDate(date)) return badRequest("date must be YYYY-MM-DD");
    const got = await fetchDigest("daily", date);
    if (!got) {
      return withCors(
        NextResponse.json(
          { error: `No daily digest for ${date}` },
          { status: 404 },
        ),
      );
    }
    return withCors(NextResponse.json({ type: "daily", ...got }));
  }

  if (week) {
    if (!isValidWeek(week)) return badRequest("week must be YYYY-Www");
    const got = await fetchDigest("weekly", week);
    if (!got) {
      return withCors(
        NextResponse.json(
          { error: `No weekly digest for ${week}` },
          { status: 404 },
        ),
      );
    }
    return withCors(NextResponse.json({ type: "weekly", ...got }));
  }

  if (!start || !end) {
    return badRequest("Range requires both start and end");
  }
  if (!isValidDate(start)) return badRequest("start must be YYYY-MM-DD");
  if (!isValidDate(end)) return badRequest("end must be YYYY-MM-DD");
  if (start > end) return badRequest("start must be ≤ end");

  const dates = enumerateDates(start, end);
  if (dates.length > MAX_RANGE_DAYS) {
    return badRequest(`Range exceeds ${MAX_RANGE_DAYS} days`);
  }

  const fetched = await Promise.all(
    dates.map((d) => fetchDigest("daily", d)),
  );
  const items = fetched.filter((x): x is NonNullable<typeof x> => x !== null);
  const missing = dates.filter(
    (d) => !items.some((it) => it.label === d),
  );

  return withCors(
    NextResponse.json({
      type: "range",
      start,
      end,
      requested: dates.length,
      found: items.length,
      missing,
      items,
    }),
  );
}
