/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow remote photo URLs from the MBUSA inventory feed.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "content.homenetiol.com" },
      { protocol: "https", hostname: "*.homenetiol.com" },
    ],
  },
  // /v2 is a vanilla static page (per HANDOFF_dashboard_v2.md). Without
  // this rewrite, /v2 (no trailing slash) 404s; only /v2/index.html works.
  //
  // /data/* proxies to the watcher's raw.githubusercontent.com URL. v2's
  // browser-side fetch hits same-origin /data/latest.json — Vercel
  // forwards to GH server-side and returns the response. raw GH doesn't
  // set Access-Control-Allow-Origin, so a direct cross-origin fetch from
  // the browser would be CORS-blocked. v1's server-side App Router fetch
  // doesn't hit this; v2 does.
  async rewrites() {
    return [
      { source: "/v2", destination: "/v2/index.html" },
      {
        source: "/data/:path*",
        destination:
          "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/data/:path*",
      },
      // /digest/* mirrors /data/* — the watcher writes weekly digests to
      // digest/weekly/<ISO-week>.md and daily digests to digest/daily/
      // <YYYY-MM-DD>.md at the repo root. Vercel proxies same-origin
      // requests to raw GH so the dashboard (and external readers) can
      // fetch them without committing the files into dashboard/public/
      // (which would otherwise trigger a Vercel rebuild on every cron).
      //
      // The two bare-/digest entries serve the archive index. They have to
      // come BEFORE the catch-all because /digest/:path* would otherwise
      // match the empty-path case and proxy to raw GH's directory URL,
      // which 404s. Order matters — Next.js takes the first match.
      {
        source: "/digest",
        destination:
          "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest/index.html",
      },
      {
        source: "/digest/",
        destination:
          "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest/index.html",
      },
      {
        source: "/digest/:path*",
        destination:
          "https://raw.githubusercontent.com/pwysocan-droid/wagon-watcher/main/digest/:path*",
      },
    ];
  },
};

export default nextConfig;
