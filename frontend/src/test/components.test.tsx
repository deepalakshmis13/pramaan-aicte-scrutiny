import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StatusTag, stateInfo } from '../components/ui/status'
import { R, homeFor, safeInternal } from '../lib/routes'
import { qs } from '../lib/api'
import Login from '../pages/auth/Login'
import { AuthProvider } from '../lib/auth'

describe('status marks', () => {
  it('distinguishes unavailable and simulated results from verified', () => {
    expect(stateInfo('verified').tone).toBe('ok')
    expect(stateInfo('source_unavailable').tone).not.toBe('ok')
    expect(stateInfo('simulated').label).toMatch(/not verified/i)
    expect(stateInfo('manual_review').tone).toBe('warn')
  })
  it('renders a label next to a shape glyph (not colour alone)', () => {
    const { container } = render(<StatusTag state="mismatch" />)
    expect(screen.getByText('Mismatch detected')).toBeInTheDocument()
    expect(container.querySelector('svg')).not.toBeNull()
  })
})

describe('routes', () => {
  it('builds stable nested paths', () => {
    expect(R.reviewer.app(3)).toBe('/reviewer/applications/3')
    expect(R.reviewer.app(3, 'notices')).toBe('/reviewer/applications/3#notices')
    expect(R.institution.notice(5)).toBe('/institution/notices/5')
    expect(homeFor('institution')).toBe('/institution')
    expect(homeFor(undefined)).toBe('/login')
  })
  it('rejects external links from notifications', () => {
    expect(safeInternal('//evil.example')).toBeNull()
    expect(safeInternal('https://evil.example')).toBeNull()
    expect(safeInternal('/reviewer/notices/1')).toBe('/reviewer/notices/1')
  })
  it('serialises only meaningful query params', () => {
    expect(qs({ a: 1, b: '', c: undefined, d: false, e: true })).toBe('?a=1&e=true')
  })
})

describe('login form', () => {
  it('validates before calling the server', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ user: null }), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(fetchMock.mock.calls.every((c: any) => !String(c[0]).includes('/auth/login'))).toBe(true)
  })
})
