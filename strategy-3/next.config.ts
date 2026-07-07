import type { NextConfig } from "next";

const backendProxyTarget =
  process.env.BACKEND_PROXY_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8002";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/dashboard", destination: "/", permanent: false },
      { source: "/dashboard/profile", destination: "/strategy-settings", permanent: false },
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
