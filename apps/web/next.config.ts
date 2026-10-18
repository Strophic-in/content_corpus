import type { NextConfig } from "next";

// Environment: lib/env.ts loads the repo-root .env for server code.
// standalone: `next build` emits a self-contained server.js, which is all the
// Docker image ships (see Dockerfile).
// staleTimes.dynamic: a tab visited in the last 30 s opens from the browser's copy at
// once (every page here is dynamic, so by default each visit waited on the server).
// Any save (server actions refresh) still shows fresh data straight away.
const nextConfig: NextConfig = {
  output: "standalone",
  experimental: { staleTimes: { dynamic: 30 } },
};

export default nextConfig;
