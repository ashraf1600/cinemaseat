import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Proxy `/api/*` to the Django backend during `vite dev` so the SPA can
// fetch using same-origin URLs (no CORS preflight needed). Override with
// the VITE_API_TARGET env var if the backend lives elsewhere (Docker,
// staging, etc.).
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
})