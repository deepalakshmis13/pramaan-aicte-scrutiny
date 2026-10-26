import { expect, test, type Page } from '@playwright/test'

const ROLES: Record<string, { email: string; pw: string; routes: string[] }> = {
  reviewer: {
    email: 'anitha.raman@scrutiny.test', pw: 'Reviewer@2026',
    routes: ['/reviewer', '/reviewer/applications', '/reviewer/applications?status=notice_issued', '/reviewer/notices', '/reviewer/audit', '/profile', '/notifications',
      '/reviewer/applications/3', '/reviewer/applications/4', '/reviewer/applications/7', '/reviewer/applications/1'],
  },
  institution: {
    email: 'principal@kaveri-valley.test', pw: 'Institution@2026',
    routes: ['/institution', '/institution/applications', '/institution/applications/new', '/institution/applications/1', '/institution/applications/9', '/institution/notices'],
  },
  admin: {
    email: 'admin@scrutiny.test', pw: 'Admin@2026',
    routes: ['/admin', '/admin/configuration', '/admin/configuration?section=checklists', '/admin/configuration?section=rules', '/admin/configuration?section=sources', '/admin/audit'],
  },
}

async function login(page: Page, email: string, pw: string) {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(pw)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).not.toHaveURL(/\/login/)
}

for (const [role, cfg] of Object.entries(ROLES)) {
  test(`every ${role} route renders without errors or dead links`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(`${page.url()}: ${e.message}`))
    page.on('console', (m) => m.type() === 'error' && errors.push(`${page.url()}: ${m.text()}`))
    await login(page, cfg.email, cfg.pw)
    for (const r of cfg.routes) {
      await page.goto(r)
      await page.waitForLoadState('networkidle')
      await expect(page.getByText('Could not load this view'), r).toHaveCount(0)
      await expect(page.getByText('Page not found'), r).toHaveCount(0)
      await expect(page.locator('h1, h2').first(), r).toBeVisible()
      const bad = await page.$$eval('a', (as) => as.map((a) => a.getAttribute('href')).filter((h) => !h || h === '#' || h.startsWith('javascript')))
      expect(bad, `dead links on ${r}`).toEqual([])
    }
    expect(errors).toEqual([])
  })
}

test('layouts do not overflow horizontally on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const [role, cfg] of Object.entries(ROLES)) {
    await login(page, cfg.email, cfg.pw)
    for (const r of cfg.routes.slice(0, 4)) {
      await page.goto(r)
      await page.waitForLoadState('networkidle')
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${role} ${r}`).toBeLessThanOrEqual(1)
    }
  }
})
