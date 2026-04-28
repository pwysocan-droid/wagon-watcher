# wagon-watcher dashboard

Next.js 15 (App Router, TypeScript) dashboard for the wagon-watcher
data. Fetches `data/latest.json` from the watcher repo's raw GitHub URL
via Incremental Static Regeneration — no rebuild needed when the
watcher commits new data; the page revalidates every 10 minutes.

## Local dev

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000.

## Vercel deploy (one-time setup)

1. Sign in at vercel.com with the GitHub account that owns the repo
2. **New Project** → import `pwysocan-droid/wagon-watcher`
3. Set **Root Directory** to `dashboard` (not the repo root)
4. **Framework Preset** auto-detects to Next.js
5. Default Build Command (`next build`) and Output Directory (`.next`) are correct
6. **Deploy**

## Skipping rebuilds on data-only commits

The watcher's cron auto-commits to `main` every 30 min, but only data
files (`data/`, `raw_snapshots/`, `alerts/`, `digest/`) change — the
dashboard's source code at `dashboard/` doesn't.

Vercel rebuilds anyway by default. To skip, in Project Settings → Git:

**Ignored Build Step** → use this command:

```bash
git diff --quiet HEAD^ HEAD ./
```

Vercel runs this from the project's Root Directory (`dashboard/`).
Exit 0 = no changes in `dashboard/` → skip rebuild. Exit 1 = changes
exist → rebuild. This means rebuilds only happen when the dashboard
source itself changes.

## Schema source of truth

The shape of `latest.json` is defined by `run.write_latest_json()` in
the watcher repo. Keep `app/types.ts` in sync when that function's
payload changes.
