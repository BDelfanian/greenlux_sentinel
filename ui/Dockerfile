# Operator UI container (ui/, Next.js 16) -- what infra/modules/container-apps-ui.bicep deploys
# onto a second Container App, alongside the agent API's own (infra/modules/container-apps.bicep).
# AGENT_API_URL/AGENT_API_TOKEN are read server-side only (src/lib/agent-api.ts, Server Actions),
# supplied as plain container env vars at runtime -- never baked into the image, never sent to
# the browser bundle (same "server-only" boundary ui/README.md already documents for local dev).

FROM node:24-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# Standalone output (next.config.ts) -- only the traced dependencies + build output, not the
# full node_modules, same "slim image" reasoning as the agent API's python:3.12-slim base.
FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
