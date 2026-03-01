/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { dev }) => {
    // Windows dev environments can hit EPERM rename races in filesystem webpack cache.
    // Disable cache in dev unless explicitly re-enabled.
    if (dev && process.env.NEXT_DEV_WEBPACK_CACHE !== "on") {
      config.cache = false;
    }
    return config;
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8080/:path*', // Proxy to Python backend
      },
    ];
  },
};

export default nextConfig;
