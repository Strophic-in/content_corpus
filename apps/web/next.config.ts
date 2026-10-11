import type { NextConfig } from "next";

// Environment: lib/env.ts loads the repo-root .env for server code.
// standalone: `next build` emits a self-contained server.js, which is all the
// Docker image ships (see Dockerfile).
const nextConfig: NextConfig = { output: "standalone" };

export default nextConfig;
