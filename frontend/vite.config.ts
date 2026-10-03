import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
  server: {
    host: "0.0.0.0",
    port: 8643,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8642",
        changeOrigin: true,
      },
    },
  },
})
