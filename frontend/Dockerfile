# Multi-stage build: compile SvelteKit static output, then serve with nginx.
# adapter-static writes to /app/build (SPA fallback = index.html).

FROM node:20-alpine AS build
WORKDIR /app

# Railway passes service variables to Dockerfile builds as ARGs.
# Promote to ENV so Vite inlines them into the built bundle.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache gettext
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Railway injects $PORT; the deploy also needs $BACKEND_URL (e.g.
# http://backend.railway.internal:8000) so nginx can reverse-proxy
# /api and /auth onto the backend service. Substituted at container
# start so Railway env vars take effect without rebuilding.
CMD ["/bin/sh", "-c", "envsubst '$PORT $BACKEND_URL' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
