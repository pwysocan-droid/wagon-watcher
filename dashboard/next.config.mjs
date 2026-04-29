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
    ];
  },
};

export default nextConfig;
