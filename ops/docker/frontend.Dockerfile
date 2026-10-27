# KGKG frontend image (Next.js). NEXT_PUBLIC_* values are baked in at build
# time; runtime settings and secrets come from the env file at `docker run`.
FROM node:20-bookworm-slim AS build
WORKDIR /app
COPY kg_frontend/package.json kg_frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY kg_frontend/ ./
ARG NEXT_PUBLIC_API_BASE=/kg-api
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM node:20-bookworm-slim
# Upgrade the base's OS packages (the pinned image lags the distribution's
# security fixes) and drop the package managers: the server starts with
# node_modules/.bin/next, and npm/yarn only bring their own bundled
# dependencies (tar, cross-spawn, ...) into the image's vulnerability count.
RUN apt-get update -q && apt-get upgrade -yq \
    && apt-get install -yq --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /opt/yarn-* \
              /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
COPY --from=build /app /app
ARG KG_RELEASE=dev
ENV KG_RELEASE=$KG_RELEASE
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=4 \
  CMD curl -fsS -o /dev/null http://127.0.0.1:${PORT}/ || exit 1
CMD exec node_modules/.bin/next start -p ${PORT} -H ${KG_BIND:-127.0.0.1}
