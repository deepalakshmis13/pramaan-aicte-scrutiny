import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { api, post } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { homeFor, safeInternal } from '../../lib/routes'
import { fmtDateTime, relative } from '../../lib/format'
import { Button, Empty, ErrorBox, KV, LoadingBlock, PageHeader } from '../../components/ui/basics'

export function Unauthorized() {
  const { user } = useAuth()
  return (
    <div className="mx-auto max-w-lg py-16">
      <h1 className="text-xl font-semibold">You don’t have access to this page</h1>
      <p className="mt-2 text-[13px] text-text-muted">
        This area belongs to a different role. You are signed in as {user?.full_name} ({user?.role}). Access is enforced by the server as well as this screen.
      </p>
      <Link to={homeFor(user?.role)} className="mt-5 inline-block text-[13px] text-link hover:underline">Go to your overview</Link>
    </div>
  )
}

export function NotFound() {
  const { user } = useAuth()
  return (
    <div className="mx-auto max-w-lg py-16">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-[13px] text-text-muted">The address doesn’t match any page. It may have been mistyped or the record may not exist.</p>
      <Link to={homeFor(user?.role)} className="mt-5 inline-block text-[13px] text-link hover:underline">Go to your overview</Link>
    </div>
  )
}

export function Profile() {
  const { user, sessionMinutes } = useAuth()
  if (!user) return null
  return (
    <div className="max-w-2xl">
      <PageHeader title="Profile and session" crumbs={[{ label: 'Home', to: homeFor(user.role) }, { label: 'Profile' }]} />
      <div className="panel p-4">
        <KV rows={[
          ['Name', user.full_name], ['Email', user.email], ['Role', { reviewer: 'Scrutiny officer', institution: 'Institution', admin: 'Administrator' }[user.role]], ['Designation', user.designation || '—'],
          ...(user.role === 'institution' ? [['Institution', user.institution_name] as [string, string]] : []),
          ['Last sign-in', fmtDateTime(user.last_login_at)], ['Session length', `${sessionMinutes / 60} hours, then sign in again`],
        ]} />
        <p className="mt-4 text-xs text-text-muted">Account changes are made by a system administrator.</p>
      </div>
    </div>
  )
}

export function NotificationsPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['notifications', 'all'], queryFn: () => api('/notifications', { params: { limit: 200 } }) })
  const readAll = useMutation({ mutationFn: () => post('/notifications/read-all'), onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }) })
  const open = async (n: any) => {
    await post(`/notifications/${n.id}/read`)
    qc.invalidateQueries({ queryKey: ['notifications'] })
    const to = safeInternal(n.link)
    if (to) nav(to)
  }
  return (
    <div className="max-w-3xl">
      <PageHeader title="Notifications" crumbs={[{ label: 'Home', to: homeFor(user?.role) }, { label: 'Notifications' }]}
        actions={<Button onClick={() => readAll.mutate()} busy={readAll.isPending} disabled={!q.data?.unread}>Mark all as read</Button>} />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.items.length === 0 ? (
        <Empty title="No notifications">Notifications about assignments, notices, responses and decisions appear here.</Empty>
      ) : (
        <ul className="panel divide-y divide-line">
          {q.data.items.map((n: any) => (
            <li key={n.id}>
              <button onClick={() => open(n)} className={clsx('flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-sunk', !n.read && 'bg-[#f4f7fd]')}>
                <span className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', n.read ? 'bg-transparent' : 'bg-link')} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-medium">{n.title}</span>
                  {n.body && <span className="block text-[12.5px] text-text-muted">{n.body}</span>}
                </span>
                <span className="shrink-0 text-xs text-text-faint">{relative(n.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

