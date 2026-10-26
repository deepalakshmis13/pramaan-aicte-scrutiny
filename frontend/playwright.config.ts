import { defineConfig, devices } from '@playwright/test'

// E2E runs against an isolated database (aicte_verify_test by default) that the
// webServer command reseeds, so your development data is never touched.
const PORT = Number(process.env.E2E_PORT ?? 8001)
const DB = process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://aicte:aicte_dev@localhost:5432/aicte_verify_test'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    command: `cd ../backend && STORAGE_DIR=../storage-e2e CROSSREF_MODE=disabled DATABASE_URL=${DB} python3 -m seed.seed --reset > /dev/null && STORAGE_DIR=../storage-e2e CROSSREF_MODE=disabled LOGIN_RATE_LIMIT_PER_MINUTE=500 DATABASE_URL=${DB} python3 -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 180_000,
    reuseExistingServer: false,
  },
})
