import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "standalone" produces .next/standalone/server.js with only the deps
  // actually needed at runtime, plus a tracing-aware node_modules tree.
  // Required for our self-host on Hetzner: systemd runs `node server.js`
  // out of /opt/aribot/web/.next/standalone/ — no global node_modules to
  // keep in sync, just the build artifact.
  //
  // Note: Next.js doesn't auto-copy public/ or .next/static/ into the
  // standalone dir. The deploy script does that post-build.
  output: "standalone",
};

export default nextConfig;
