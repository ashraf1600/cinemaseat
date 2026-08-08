# syntax=docker/dockerfile:1.7
#
# CinemaSeat client image.
#
# Multi-stage:
#   * builder  -> Node 20 Alpine, runs `npm ci && npm run build`. Output
#                  is the static `dist/` directory produced by Vite.
#   * runtime  -> nginx:alpine serving the static build. nginx also
#                  proxies `/api/*` to the `backend` service so the SPA
#                  can talk to Django without CORS preflights.
#
# Why nginx and not `vite preview`: nginx is what production actually
# uses (real HTTP server, gzip, SPA history-API fallback, low memory).
# `vite preview` is a dev tool.
# ---------------------------------------------------------------------------

ARG NODE_VERSION=20

# ---------------------------------------------------------------------------
# Stage 1: build the static bundle.
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS builder
WORKDIR /app

# Copy lockfile first so dependency install is cached unless they change.
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# Build-time env. The SPA reads VITE_API_BASE_URL at build time, baked
# into the bundle. We default to a same-origin `/api` so the nginx
# proxy handles routing — no CORS, no DNS leaks. Override at build
# time with `--build-arg VITE_API_BASE_URL=...` if the backend lives
# on a different origin.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: serve the static bundle with nginx.
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Drop the default nginx site and use ours.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static assets from the builder.
COPY --from=builder /app/dist /usr/share/nginx/html

# Non-root nginx runs as `nginx` user on port 8080 by default in the
# upstream image; we keep that and publish 8080 from the compose file.
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
