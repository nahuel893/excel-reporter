import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8010",
        changeOrigin: true,
        // Strip /api prefix — backend routes are at /mgmt/..., /ventas/..., etc.
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
      "/mgmt": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8010",
        changeOrigin: true,
      },
      "/ventas": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8010",
        changeOrigin: true,
      },
      "/resumen-mensual": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8010",
        changeOrigin: true,
      },
      "/graficos-cobertura": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8010",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8010",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
})
