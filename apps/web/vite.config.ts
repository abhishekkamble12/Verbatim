import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser talks to /api; Vite forwards it to the FastAPI server, so the API needs no CORS.
declare const process: { env: Record<string, string | undefined> }; // Node global; avoids adding @types/node

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_URL ?? "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
