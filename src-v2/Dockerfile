# syntax=docker/dockerfile:1
# Веб «Карьер» (src-v2): сборка Vite/React на Node 22, раздача статики nginx.
# Конфиг nginx (SPA fallback, /api → api, кэш статики, без sourcemap) монтируется
# из deploy/nginx.conf в /etc/nginx/conf.d/default.conf (см. docker-compose.yml).

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . ./
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Свой server-блок приходит из deploy/nginx.conf (bind mount в compose)
RUN rm -f /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

# В прод не отдаём sourcemap: удаляем .map, если они вдруг оказались в сборке
RUN find /usr/share/nginx/html -name '*.map' -delete

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
