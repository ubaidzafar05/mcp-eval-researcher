/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  webpack: (config, { dev }) => {
    // Windows dev environments can hit EPERM rename races in filesystem webpack cache.
    // Disable cache in dev unless explicitly re-enabled.
    if (dev && process.env.NEXT_DEV_WEBPACK_CACHE !== "on") {
      config.cache = false;
    }
    return config;
  },
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8080';
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
