# ---- Build stage ----
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --include=dev

COPY index.html vite.config.js ./
COPY src/ ./src/

RUN npm run build

# ---- Runtime stage: nginx serves built assets + proxies API to backend service ----
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
