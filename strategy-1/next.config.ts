import type { NextConfig } from "next";

/** Where Next rewrites `/backend-proxy/*` (server-side). Override if API is not on localhost. */
const backendProxyTarget =
  process.env.BACKEND_PROXY_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/dashboard", destination: "/", permanent: false },
      { source: "/dashboard/profile", destination: "/settings", permanent: false },
      { source: "/login", destination: "/", permanent: false },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/backend-proxy/:path*",
        destination: `${backendProxyTarget}/:path*`,
      },
    ];
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "images.unsplash.com",
        pathname: "/**",
      },
    ],
  },
};

export default nextConfig;
