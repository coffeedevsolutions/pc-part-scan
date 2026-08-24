import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@pcps/valuation"],
  images: {
    remotePatterns: [{ protocol: "https", hostname: "files.lqdt1.com" }],
  },
};

export default nextConfig;
