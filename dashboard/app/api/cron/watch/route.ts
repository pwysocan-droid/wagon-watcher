// Vercel Cron → GitHub workflow_dispatch for the watch workflow.
//
// GitHub's own `schedule` trigger drops most runs (see LEARNINGS.md), and
// dispatches aren't subject to that, so an always-on scheduler fires them.
// Vercel calls this route on the schedule in vercel.json and sends
// `Authorization: Bearer $CRON_SECRET`; anything else is rejected.
//
// Env (Vercel project settings):
//   CRON_SECRET            any random string; Vercel attaches it to cron calls
//   GITHUB_DISPATCH_TOKEN  fine-grained PAT, repo pwysocan-droid/wagon-watcher
//                          only, permission "Actions: Read and write"
export const dynamic = "force-dynamic";

const DISPATCH_URL =
  "https://api.github.com/repos/pwysocan-droid/wagon-watcher/actions/workflows/watch.yml/dispatches";

export async function GET(req: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) {
    return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    return Response.json({ ok: false, error: "GITHUB_DISPATCH_TOKEN not set" }, { status: 500 });
  }

  const res = await fetch(DISPATCH_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "wagon-watcher-vercel-cron",
    },
    body: JSON.stringify({ ref: "main" }),
    cache: "no-store",
  });

  // GitHub answers 204 No Content on success.
  if (res.status !== 204) {
    const detail = (await res.text()).slice(0, 300);
    console.error(`[cron/watch] dispatch failed ${res.status}: ${detail}`);
    return Response.json({ ok: false, status: res.status, detail }, { status: 502 });
  }
  return Response.json({ ok: true, dispatchedAt: new Date().toISOString() });
}
