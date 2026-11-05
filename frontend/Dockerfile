FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Next rewrites bake BACKEND_ORIGIN at build time (see next.config.mjs).
# Compose sets http://backend:8000 for the multi-container stack.
ARG BACKEND_ORIGIN=http://127.0.0.1:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN

RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
