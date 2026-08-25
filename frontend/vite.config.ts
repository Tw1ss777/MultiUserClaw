import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/agents/grzs/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 3080,
    proxy: {
      '/api/openclaw/events/stream': {
        target: 'http://localhost:8080',
        // Disable buffering for SSE
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache'
            proxyRes.headers['x-accel-buffering'] = 'no'
          })
        },
      },
      '/api': 'http://localhost:8080',
      // Path-prefixed variants for serving the app under /agents/grzs in dev
      '/agents/grzs/api/openclaw/events/stream': {
        target: 'http://localhost:8080',
        rewrite: (path) => path.replace(/^\/agents\/grzs/, ''),
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache'
            proxyRes.headers['x-accel-buffering'] = 'no'
          })
        },
      },
      '/agents/grzs/api': {
        target: 'http://localhost:8080',
        rewrite: (path) => path.replace(/^\/agents\/grzs/, ''),
      },
    },
  },
})
