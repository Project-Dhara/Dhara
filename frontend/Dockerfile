FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# next.config.mjs bakes BACKEND_ORIGIN into rewrites at `next build` time.
# Default is localhost (single-container / local). Compose passes
# http://backend:8000 for the split frontend service.
ARG BACKEND_ORIGIN=http://127.0.0.1:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN

RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
