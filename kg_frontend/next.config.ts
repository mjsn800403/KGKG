import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't advertise the framework in an x-powered-by header.
  poweredByHeader: false,
  // ops/deploy/deploy.sh builds each release into its own .next-<sha> and
  // swaps the .next symlink, so a build never overwrites the files the live
  // server is reading. Unset (dev, CI, next start) it is the usual .next.
  distDir: process.env.KG_NEXT_DIST || '.next',
};

export default nextConfig;
