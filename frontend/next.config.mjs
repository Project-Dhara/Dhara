/** @type {import('next').NextConfig} */
const desktopStatic = process.env.DHARA_DESKTOP_STATIC === '1'
const backendOrigin = process.env.BACKEND_ORIGIN || 'http://127.0.0.1:8000'

const nextConfig = {
  ...(desktopStatic
    ? {
        output: 'export',
        images: { unoptimized: true },
        trailingSlash: true,
      }
    : {
        // Excel batch-extract / PDF jobs can exceed the default ~30s rewrite proxy
        // timeout and fail with "socket hang up" → UI "Extraction failed".
        // Desktop Electron uploads can also be multi‑MB xlsx; keep the rewrite proxy patient.
        experimental: {
          proxyTimeout: 300_000, // 5 minutes
        },
        async rewrites() {
          // Same-origin /api and /mcp via Next rewrite for web/Docker.
          // Desktop static export serves UI from FastAPI (no rewrites).
          return [
            { source: '/api/:path*', destination: `${backendOrigin}/api/:path*` },
            { source: '/mcp', destination: `${backendOrigin}/mcp` },
            { source: '/mcp/', destination: `${backendOrigin}/mcp/` },
          ]
        },
      }),
}

export default nextConfig
