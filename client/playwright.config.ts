// Browser tests (story E01-001). Playwright runs them against the built client and the real server.
// Run with  pnpm --filter @franca/client e2e
// The pipeline and scripts/setup install Playwright's Chromium. On a computer that has Chromium elsewhere, put its path in
// FRANCA_CHROMIUM.
import { defineConfig, devices } from "@playwright/test";

declare const process: { env: Record<string, string | undefined> };

const chromium = process.env.FRANCA_CHROMIUM;

export default defineConfig({
  testDir: "e2e",
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    // localhost and not 127.0.0.1: passkeys belong to a host name, and browsers do not allow an IP address there.
    baseURL: "http://localhost:4173",
    trace: "retain-on-failure",
    launchOptions: chromium ? { executablePath: chromium } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // A new database for each run, in the server folder (database files are ignored by Git).
      command:
        "cd ../server && rm -f e2e.db && export PYTHONPATH=src FRANCA_DATABASE_PATH=e2e.db FRANCA_PUBLIC_URL=http://localhost:4173 FRANCA_OWNER_EMAIL=owner@example.org && uv run python -m franca.platform.migrate && uv run uvicorn franca.api:create_app --factory --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/api/v1/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "pnpm build && pnpm exec vite preview --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
