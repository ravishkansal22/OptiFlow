import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

// Dev server proxies /api and /ws to the FastAPI backend so the app can be
// served same-origin. Override the target with VITE_PROXY_TARGET.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
})
