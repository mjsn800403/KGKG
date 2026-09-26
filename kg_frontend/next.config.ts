import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't advertise the framework in an x-powered-by header.
  poweredByHeader: false,
};

export default nextConfig;
