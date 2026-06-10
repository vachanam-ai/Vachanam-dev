import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Backend (uvicorn) on :8000 in dev — keeps the app same-origin.
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/auth": { target: "http://localhost:8000", changeOrigin: true },
      "/queue": { target: "http://localhost:8000", changeOrigin: true },
      "/doctors": { target: "http://localhost:8000", changeOrigin: true },
      "/availability": { target: "http://localhost:8000", changeOrigin: true },
      "/branches": { target: "http://localhost:8000", changeOrigin: true },
      "/dashboard": { target: "http://localhost:8000", changeOrigin: true },
      "/admin": { target: "http://localhost:8000", changeOrigin: true }
    }
  }
});
