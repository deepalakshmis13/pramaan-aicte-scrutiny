import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Popover from '@radix-ui/react-popover'
import * as DD from '@radix-ui/react-dropdown-menu'
import { Bell, ChevronDown, LogOut, Menu, ScrollText, UserRound } from 'lucide-react'
import clsx from 'clsx'
import { useState } from 'react'
import { api, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import { R, homeFor, safeInternal } from '../lib/routes'
import { relative } from '../lib/format'

const NAV = {
  reviewer: [
    { to: R.reviewer.home, label: 'Dashboard', end: true },
    { to: R.reviewer.apps(), label: 'Applications' },
    { to: R.reviewer.notices, label: 'Notices' },
  ],
  institution: [
    { to: R.institution.home, label: 'Overview', end: true },
    { to: R.institution.apps, label: 'My Applications' },
    { to: R.institution.notices, label: 'Notices' },
  ],
  admin: [
    { to: R.admin.home, label: 'Users', end: true },
    { to: R.admin.config, label: 'Configuration' },
    { to: R.admin.audit, label: 'Audit log' },
  ],
}

export function Wordmark({ light = true }: { light?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="6" fill={light ? '#14284a' : '#0c1b33'} />
        <path d="M9 7h9a6 6 0 0 1 0 12h-5v6H9z" fill="none" stroke="#7FD1C1" strokeWidth="2.6" />
        <path d="M13 13h4" stroke="#F2F3EF" strokeWidth="2.6" />
      </svg>
      <span className="leading-none">
        <span className={clsx('block text-[15px] font-bold tracking-[0.08em]', light ? 'text-white' : 'text-ink')}>PRAMAAN</span>
        <span className={clsx('block text-[10.5px]', light ? 'text-[#9fb0cc]' : 'text-text-muted')}>Application scrutiny</span>
      </span>
    </span>
  )
}

function Notifications() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: ['notifications'], queryFn: () => api('/notifications', { params: { limit: 12 } }), refetchInterval: 30_000 })
  const read = useMutation({
    mutationFn: (id: number) => post(`/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const unread = q.data?.unread ?? 0
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button className="relative rounded p-2 text-[#c9d4e6] hover:bg-ink-3 hover:text-white" aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`}>
          <Bell className="h-[18px] w-[18px]" />
          {unread > 0 && <span className="absolute right-1 top-1 min-w-[16px] rounded-full bg-[#e8a33d] px-1 text-[10px] font-bold leading-4 text-ink">{unread}</span>}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={6} className="z-50 w-[min(380px,calc(100vw-24px))] rounded-md border border-line bg-surface shadow-pop">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <span className="text-[13px] font-semibold">Notifications</span>
            <Link to={R.notifications} onClick={() => setOpen(false)} className="text-xs text-link hover:underline">View all</Link>
          </div>
          <ul className="max-h-[60vh] overflow-y-auto">
            {(q.data?.items ?? []).length === 0 && <li className="px-3 py-4 text-[13px] text-text-muted">No notifications yet.</li>}
            {(q.data?.items ?? []).map((n: any) => (
              <li key={n.id}>
                <button
                  className={clsx('block w-full border-b border-line px-3 py-2.5 text-left hover:bg-sunk', !n.read && 'bg-[#f4f7fd]')}
                  onClick={async () => {
                    await read.mutateAsync(n.id)
                    setOpen(false)
                    const to = safeInternal(n.link)
                    if (to) nav(to)
                  }}
                >
                  <div className="flex items-start gap-2">
                    {!n.read && <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-link" aria-label="unread" />}
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium">{n.title}</div>
                      {n.body && <div className="truncate text-xs text-text-muted">{n.body}</div>}
                      <div className="mt-0.5 text-[11px] text-text-faint">{relative(n.created_at)}</div>
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

export default function AppShell() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [mobile, setMobile] = useState(false)
  const items = user ? NAV[user.role] : []
  const logout = async () => {
    try {
      await post('/auth/logout')
    } finally {
      qc.clear()
      nav(R.login, { replace: true })
    }
  }
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <header className="bg-ink text-text-inverse">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-6 px-4">
          <Link to={homeFor(user?.role)} className="shrink-0" aria-label="PRAMAAN home"><Wordmark /></Link>
          <nav className="hidden flex-1 items-center gap-1 lg:flex" aria-label="Main">
            {items.map((i) => (
              <NavLink key={i.to} to={i.to} end={(i as any).end}
                className={({ isActive }) => clsx('rounded px-3 py-1.5 text-[13px] font-medium', isActive ? 'bg-ink-3 text-white' : 'text-[#b8c5da] hover:bg-ink-2 hover:text-white')}>
                {i.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <Notifications />
            <DD.Root>
              <DD.Trigger asChild>
                <button className="flex items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-ink-2" aria-label="Account menu">
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-ink-3 text-xs font-semibold text-white">{user?.full_name.replace(/^(Dr\.|Principal,)\s*/, '').slice(0, 1)}</span>
                  <span className="hidden leading-tight md:block">
                    <span className="block max-w-[200px] truncate text-[12.5px] font-medium text-white">{user?.full_name}</span>
                    <span className="block text-[11px] text-[#9fb0cc]">{user?.role === 'institution' ? user.institution_name : user?.role === 'reviewer' ? 'Scrutiny Officer' : 'Administrator'}</span>
                  </span>
                  <ChevronDown className="h-3.5 w-3.5 text-[#9fb0cc]" />
                </button>
              </DD.Trigger>
              <DD.Portal>
                <DD.Content align="end" sideOffset={6} className="z-50 min-w-[200px] rounded-md border border-line bg-surface p-1 text-[13px] shadow-pop">
                  <DD.Item onSelect={() => nav(R.profile)} className="flex cursor-pointer items-center gap-2 rounded px-2.5 py-1.5 outline-none data-[highlighted]:bg-sunk"><UserRound className="h-4 w-4" />Profile and session</DD.Item>
                  {user?.role === 'reviewer' && <DD.Item onSelect={() => nav(R.reviewer.audit)} className="flex cursor-pointer items-center gap-2 rounded px-2.5 py-1.5 outline-none data-[highlighted]:bg-sunk"><ScrollText className="h-4 w-4" />Audit trail</DD.Item>}
                  <DD.Separator className="my-1 h-px bg-line" />
                  <DD.Item onSelect={logout} className="flex cursor-pointer items-center gap-2 rounded px-2.5 py-1.5 text-bad outline-none data-[highlighted]:bg-bad-soft"><LogOut className="h-4 w-4" />Sign out</DD.Item>
                </DD.Content>
              </DD.Portal>
            </DD.Root>
            <button className="rounded p-2 text-[#c9d4e6] hover:bg-ink-2 lg:hidden" aria-label="Open menu" aria-expanded={mobile} onClick={() => setMobile((m) => !m)}>
              <Menu className="h-5 w-5" />
            </button>
          </div>
        </div>
        {mobile && (
          <nav className="border-t border-ink-3 px-2 py-2 lg:hidden" aria-label="Main mobile">
            {items.map((i) => (
              <NavLink key={i.to} to={i.to} end={(i as any).end} onClick={() => setMobile(false)}
                className={({ isActive }) => clsx('block rounded px-3 py-2 text-[13px]', isActive ? 'bg-ink-3 text-white' : 'text-[#b8c5da]')}>
                {i.label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <div className="border-b border-warn/30 bg-warn-soft">
        <p className="mx-auto max-w-[1440px] px-4 py-1 text-[11.5px] text-warn">
          Prototype with synthetic test data. Not connected to AICTE systems; automated results support, and never replace, an authorised officer’s judgement.
        </p>
      </div>
      <main id="main" className="mx-auto max-w-[1440px] px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
