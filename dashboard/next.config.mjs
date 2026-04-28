/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow remote photo URLs from the MBUSA inventory feed.
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "content.homenetiol.com" },
      { protocol: "https", hostname: "*.homenetiol.com" },
    ],
  },
};

export default nextConfig;
