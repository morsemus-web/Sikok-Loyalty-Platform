# ---- Build stage ----
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --include=dev

COPY index.html admin.html vite.config.js ./
COPY src/ ./src/

RUN npm run build

# ---- Runtime stage: Caddy serves built assets + auto-TLS + backend proxy ----
FROM caddy:2-alpine

COPY --from=builder /app/dist /usr/share/caddy
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443

# Caddy entrypoint runs `caddy run --config /etc/caddy/Caddyfile`
