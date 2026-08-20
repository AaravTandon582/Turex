import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /**
   * Trace the files the server actually needs and emit them alongside a small server.
   *
   * Without this a container image has to carry `node_modules` whole — hundreds of megabytes,
   * nearly all of it build tooling that never runs in production.
   */
  output: "standalone",
};

export default nextConfig;
