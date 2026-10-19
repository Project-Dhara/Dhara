FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# next.config.mjs uses BACKEND_ORIGIN for /api rewrites.
# Default is localhost (single-container / local). Compose passes
# http://backend:8000 for the split frontend service.
ARG BACKEND_ORIGIN=http://127.0.0.1:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN

EXPOSE 3000
# Testing: Next.js dev server (no production build).
CMD ["npm", "run", "dev"]
