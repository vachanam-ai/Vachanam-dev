import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Several backend prefixes (/availability, /doctors, /admin, ...) are ALSO
// React Router page routes. A plain proxy sent full-page reloads of those
// routes to FastAPI -> {"detail":"Not Found"}. bypass(): browser navigations
// (Accept: text/html) get index.html (SPA takes over); XHR/fetch JSON calls
// proxy through to uvicorn.
const toBackend = {
  target: "http://localhost:8000",
  changeOrigin: true,
  bypass(req) {
    if (req.headers.accept?.includes("text/html")) return "/index.html";
  }
};

export default defineConfig({
  plugins: [react()],
  // Vitest: jsdom so React components render to a DOM in tests; globals so
  // describe/it/expect need no imports; setup wires @testing-library/jest-dom
  // matchers. Scoped to src/**/*.test.jsx — never touches backend/python.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    include: ["src/**/*.{test,spec}.{js,jsx}"]
  },
  server: {
    port: 3000,
    proxy: {
      "/api": toBackend,
      "/auth": toBackend,
      "/queue": toBackend,
      "/doctors": toBackend,
      "/availability": toBackend,
      "/branches": toBackend,
      "/dashboard": toBackend,
      "/admin": toBackend,
      "/analytics": toBackend
    }
  }
});
