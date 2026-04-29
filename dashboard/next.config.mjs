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
  async rewrites() {
    return [
      { source: "/v2", destination: "/v2/index.html" },
    ];
  },
};

export default nextConfig;
