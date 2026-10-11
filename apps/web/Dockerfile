# The web app as a small standalone Node server. Built and run by
# deploy/docker-compose.yml; configuration comes from the environment at runtime
# (the repo-root .env via env_file), nothing is baked into the image.

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN useradd --uid 10001 --create-home web
COPY --from=build --chown=web /app/.next/standalone ./
COPY --from=build --chown=web /app/.next/static ./.next/static
COPY --from=build --chown=web /app/public ./public
# The shipped default prompts: where new formats start, and "Reset to default".
COPY --from=prompts --chown=web . ./prompts
ENV PROMPTS_DIR=/app/prompts
USER web
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
