# OpenNotebook web image: Angular SPA served by unprivileged nginx, which also proxies /api to the api service.

FROM node:24.22.2-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx ng build --configuration production

FROM nginxinc/nginx-unprivileged:1.31.7-alpine
# Security updates of the Alpine base published after the image was built, then back to the nginx user.
USER root
RUN apk upgrade --no-cache
USER 101
ARG VERSION=dev
LABEL org.opencontainers.image.title="OpenNotebook web" \
      org.opencontainers.image.description="OpenNotebook web UI (Angular) served by unprivileged nginx; proxies /api to the api service." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/lordraw77/OpenNotebook" \
      org.opencontainers.image.url="https://hub.docker.com/r/lordraw/opennotebook-web"
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /src/dist/frontend/browser /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1
