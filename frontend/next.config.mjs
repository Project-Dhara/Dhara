/** @type {import('next').NextConfig} */
const backendOrigin = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000'

const nextConfig = {
  async rewrites() {
    // Mirrors Vite's old dev proxy (VITE_API_PROXY) -- every component's
    // fetch('/api/...') call stays unchanged, forwarded to the FastAPI
    // backend, same-origin, so no CORS/base-URL plumbing is needed anywhere
    // else in the app.
    return [
      { source: '/api/:path*', destination: `${backendOrigin}/api/:path*` },
    ]
  },
}

export default nextConfig
