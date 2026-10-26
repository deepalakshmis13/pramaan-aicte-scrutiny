import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const OFFICER = { email: 'anitha.raman@scrutiny.test', pw: 'Reviewer@2026' }
const OFFICER2 = { email: 'vikram.sethi@scrutiny.test', pw: 'Reviewer@2026' }
const INST = { email: 'director@northfield.test', pw: 'Institution@2026' }
const OTHER_INST = { email: 'principal@aranya.test', pw: 'Institution@2026' }

async function login(page: Page, who: { email: string; pw: string }) {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email)
  await page.getByLabel('Password').fill(who.pw)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).not.toHaveURL(/\/login/)
}
const toast = (page: Page, text: string | RegExp) => page.locator('[data-sonner-toast]', { hasText: text }).last()

function consoleGuard(page: Page) {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => { if (m.type() === 'error' && !/status of (404|409|415|422)/.test(m.text())) errors.push(m.text()) })
  return errors
}

test('institution submits → officer verifies → notice reaches the institution → response → decision', async ({ page }) => {
  test.setTimeout(240_000)
  const errors = consoleGuard(page)

  // 1. Institution creates an application and sees the checklist
  await login(page, INST)
  await page.getByRole('link', { name: 'My Applications' }).click()
  await page.getByRole('button', { name: 'New Application' }).click()
  await page.getByLabel('Application type').selectOption('INC')
  await page.getByLabel('Academic year').fill('2028-29')
  await page.getByLabel('Total approved intake').fill('360')
  await expect(page.getByText(/needs \d+ required documents/)).toBeVisible()
  await page.getByRole('button', { name: 'Create application and continue' }).click()
  await expect(page.getByText('Draft — not yet submitted').first()).toBeVisible()
  const instAppUrl = page.url()
  const reference = (await page.locator('h1').innerText()).trim()

  // submitting too early lists what is missing
  await page.getByRole('button', { name: 'Submit application' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Submit application' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Upload the' })).toBeVisible()

  // 2. Upload every document on the checklist
  const dir = path.join(HERE, 'fixtures', 'northfield')
  for (const f of fs.readdirSync(dir).sort()) {
    const type = f.replace(/-\d+\.(pdf|png)$/, '')
    const row = page.getByTestId(`check-${type}`)
    await row.getByLabel(/^(Upload|Add another) file$/).setInputFiles(path.join(dir, f))
    await expect(row.getByText(f)).toBeVisible({ timeout: 30_000 })
  }
  await expect(page.getByText('All required documents uploaded')).toBeVisible()
  await page.getByRole('button', { name: 'Submit application' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Submit application' }).click()
  await expect(toast(page, /submitted\. It is now with the scrutiny officer/)).toBeVisible()
  await expect(page.getByText('Received — awaiting scrutiny').first()).toBeVisible()

  // 3. Officer finds it in the queue and verifies it
  await login(page, OFFICER)
  await page.getByRole('link', { name: 'Applications' }).click()
  await page.getByLabel('Search').fill(reference)
  await page.keyboard.press('Enter')
  await page.getByRole('link', { name: reference }).click()
  await expect(page.getByRole('heading', { name: 'Northfield Institute of Technology' })).toBeVisible()
  const appUrl = page.url().split('#')[0]
  await page.getByRole('button', { name: 'Verify Application' }).click()
  await expect(toast(page, 'Verification finished')).toBeVisible({ timeout: 120_000 })
  const nocRow = page.getByRole('row', { name: /No Objection Certificate/ }).first()
  await expect(nocRow.getByText('Expired')).toBeVisible()

  // open a document: page image, OCR text and extracted fields on the same page
  await nocRow.getByRole('button', { name: 'Open' }).click()
  const drawer = page.getByRole('dialog')
  await expect(drawer.getByRole('img', { name: 'Page 1' })).toBeVisible()
  await drawer.getByRole('tab', { name: 'OCR / text' }).click()
  await expect(drawer.getByText(/NO OBJECTION CERTIFICATE/)).toBeVisible()
  await page.keyboard.press('Escape')

  // 4. Reject the expired NOC with a reason, accept everything else
  await nocRow.getByRole('button', { name: 'Reject' }).click()
  await page.getByRole('dialog').getByLabel('Reason for rejection').fill('The NOC expired before the academic year. Submit a currently valid NOC.')
  await page.getByRole('dialog').getByRole('button', { name: 'Reject document' }).click()
  await expect(toast(page, 'Document rejected')).toBeVisible()
  for (let i = 0; i < 20; i++) {
    const row = page.locator('#documents tbody tr').filter({ has: page.getByRole('button', { name: 'Accept', exact: true }) }).filter({ hasNotText: /No Objection Certificate/ }).first()
    if (!(await row.count())) break
    await row.getByRole('button', { name: 'Accept', exact: true }).click()
    const dlg = page.getByRole('dialog')
    const note = dlg.getByLabel('Note')
    if (await note.count()) await note.fill('Checked against the original document; acceptable.')
    await dlg.getByRole('button', { name: 'Accept document' }).click()
    await expect(dlg).toBeHidden()
  }

  // 5. Create and send the deficiency notice
  await page.getByRole('button', { name: 'Create Deficiency Notice' }).click()
  const form = page.getByRole('dialog')
  await expect(form.getByText(/Document rejected: No Objection Certificate/)).toBeVisible()
  await form.getByRole('button', { name: /Review notice/ }).click()
  await form.getByRole('button', { name: 'Send Notice' }).click()
  await expect(toast(page, /sent to Northfield Institute of Technology/)).toBeVisible()
  await expect(page.getByText(/DN-.*· Sent — awaiting response/)).toBeVisible()

  // another institution does not see it
  await login(page, OTHER_INST)
  await page.getByRole('link', { name: 'Notices' }).click()
  await expect(page.getByText(reference)).toHaveCount(0)

  // 6. The institution sees the notice on Overview and Notices, responds with a corrected NOC
  await login(page, INST)
  await expect(page.getByText(/Respond to deficiency notice DN-/).first()).toBeVisible()
  await page.getByRole('link', { name: 'Notices' }).click()
  await page.getByRole('row', { name: new RegExp(reference) }).click()
  await expect(page.getByText(/expired before the academic year/).first()).toBeVisible()
  for (let i = 0; i < 10; i++) {
    const boxes = page.getByLabel('Your response or clarification')
    const n = await boxes.count()
    if (!n) break
    const item = page.locator('li', { has: boxes.first() })
    const file = item.locator('input[type=file]')
    if (await item.getByText(/No Objection/).count()) await file.setInputFiles(path.join(HERE, 'fixtures', 'noc-corrected.pdf'))
    await boxes.first().fill('Corrected document and clarification attached.')
    await item.getByRole('button', { name: 'Save response' }).click()
    await expect(boxes).toHaveCount(n - 1)
  }
  await page.getByRole('button', { name: 'Submit response' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Submit response' }).click()
  await expect(toast(page, /Response submitted/)).toBeVisible()
  await expect(page).toHaveURL(instAppUrl)

  // 7. Officer reviews the corrected document and accepts it
  await login(page, OFFICER)
  await page.goto(appUrl)
  const noc2 = page.getByRole('row', { name: /No Objection Certificate/ }).first()
  await expect(noc2.getByText(/version 2/)).toBeVisible({ timeout: 60_000 })
  await noc2.getByRole('button', { name: 'Accept', exact: true }).click()
  const dlg = page.getByRole('dialog')
  if (await dlg.getByLabel('Note').count()) await dlg.getByLabel('Note').fill('Corrected NOC verified.')
  await dlg.getByRole('button', { name: 'Accept document' }).click()
  await expect(toast(page, 'Document accepted')).toBeVisible()
  for (let i = 0; i < 10; i++) {
    const b = page.locator('#notices').getByRole('button', { name: 'Mark resolved' }).first()
    if (!(await b.count())) break
    await b.click()
    await page.getByRole('dialog').getByLabel('Note').fill('Clarification accepted.')
    await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
  }
  await page.getByRole('button', { name: 'Move to decision' }).click()
  await expect(toast(page, 'Moved to decision')).toBeVisible()

  // 8. An officer records the final decision
  await login(page, OFFICER2)
  await page.goto(appUrl + '#decision')
  await page.getByLabel('Approved', { exact: true }).check()
  await page.getByLabel('Reasons').fill('All mandatory documents are present and verified after correction.')
  const ack = page.getByText(/record this decision with them open/)
  if (await ack.isVisible()) await ack.click()
  await page.getByRole('button', { name: 'Record decision' }).click()
  await expect(toast(page, 'Decision recorded')).toBeVisible()

  await login(page, INST)
  await page.goto(instAppUrl)
  await expect(page.getByText('Decision recorded').first()).toBeVisible()
  expect(errors).toEqual([])
})

test('invalid ids, unauthorised URLs and refresh', async ({ page }) => {
  await login(page, OFFICER)
  await page.goto('/reviewer/applications/99999')
  await expect(page.getByText('Not found', { exact: true })).toBeVisible()
  await page.goto('/admin')
  await expect(page.getByText('You don’t have access to this page')).toBeVisible()
  await page.goto('/reviewer/applications/1')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Kaveri Valley College of Engineering' })).toBeVisible()
  await page.goto('/reviewer/no-such-page')
  await expect(page.getByText('Page not found')).toBeVisible()
  await login(page, INST)
  await page.goto('/institution/applications/1')
  await expect(page.getByText('Not found', { exact: true })).toBeVisible()
  await page.goto('/reviewer')
  await expect(page.getByText('You don’t have access to this page')).toBeVisible()
})

test('unavailable external sources are labelled, never verified', async ({ page }) => {
  await login(page, OFFICER2)
  await page.goto('/reviewer/applications/5#verification')
  await page.getByLabel('Show passing checks too').check()
  await expect(page.getByText('External verification unavailable').first()).toBeVisible()
  await expect(page.locator('#verification').getByText('Publication metadata').first()).toBeVisible()
})

test('server errors produce an error state, not a blank page', async ({ page }) => {
  await login(page, OFFICER)
  await page.route('**/api/reviewer/dashboard', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { status: 500, message: 'Internal server error.' } }) }))
  await page.goto('/reviewer')
  await expect(page.getByText('Could not load this view')).toBeVisible()
})
