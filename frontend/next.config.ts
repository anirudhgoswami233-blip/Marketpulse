import type { NextConfig } from "next";

// Set in production (Vercel): the backend's own URL. The browser then calls this site's /api/v1/*, which is proxied
// there, so the refresh cookie stays first-party (the frontend and backend hosts are different sites).
const backendUrl = process.env.API_BASE_URL?.replace(/\/+$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  async rewrites() {
    return backendUrl ? [{ source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` }] : [];
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
