import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Strip /api prefix — backend routes are at /mgmt/..., /ventas/..., etc.
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
      "/mgmt": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ventas": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/resumen-mensual": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/graficos-cobertura": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
})
