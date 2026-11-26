/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development and in the browser tests, API calls go to the server on port 8000, so the client and the API
// share one origin.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  preview: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { sourcemap: true },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
    restoreMocks: true,
  },
});
