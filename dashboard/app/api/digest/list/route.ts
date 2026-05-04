import { NextResponse } from "next/server";

const INDEX_URL =
  "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest/index.json";
const FETCH_REVALIDATE_S = 600;

type Item = { label: string; href: string; size_bytes: number };
type Manifest = {
  generated_at: string;
  weekly: Item[];
  daily: Item[];
};

function withCors(res: NextResponse): NextResponse {
  res.headers.set("Access-Control-Allow-Origin", "*");
  res.headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  return res;
}

export async function OPTIONS() {
  return withCors(new NextResponse(null, { status: 204 }));
}

export async function GET() {
  const res = await fetch(INDEX_URL, {
    next: { revalidate: FETCH_REVALIDATE_S },
  });
  if (!res.ok) {
    return withCors(
      NextResponse.json(
        { error: `Manifest fetch failed: ${res.status}` },
        { status: 502 },
      ),
    );
  }
  const m = (await res.json()) as Manifest;

  const total =
    (m.weekly?.length ?? 0) + (m.daily?.length ?? 0);
  const totalBytes =
    [...(m.weekly ?? []), ...(m.daily ?? [])]
      .reduce((acc, x) => acc + (x.size_bytes ?? 0), 0);

  return withCors(
    NextResponse.json({
      generated_at: m.generated_at,
      total_count: total,
      total_bytes: totalBytes,
      weekly: {
        count: m.weekly?.length ?? 0,
        items: m.weekly ?? [],
      },
      daily: {
        count: m.daily?.length ?? 0,
        items: m.daily ?? [],
      },
    }),
  );
}
