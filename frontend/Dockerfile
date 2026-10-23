FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Dev server reads BACKEND_ORIGIN at startup (next.config.mjs rewrites).
# Compose sets http://backend:8000. `next build` is only for the prod image.
ARG BACKEND_ORIGIN=http://127.0.0.1:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN

EXPOSE 3000
CMD ["npm", "run", "dev"]
