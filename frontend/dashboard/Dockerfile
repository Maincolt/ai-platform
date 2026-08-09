# Multi-stage build: compile the static Vue bundle, then serve it from a
# minimal nginx image that also reverse-proxies /api and /health to the
# platform container -- the same relative-path fetch() calls this app
# already uses in local dev (vite.config.js's dev-server proxy) work
# unchanged here, so there is exactly one frontend code path, not two.

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
