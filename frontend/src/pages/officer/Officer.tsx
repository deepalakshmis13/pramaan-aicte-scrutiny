import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { toast } from 'sonner'
import { Download, Search } from 'lucide-react'
import { api, errorMessage, openFile, qs } from '../../lib/api'
import { useMeta } from '../../lib/meta'
import { R } from '../../lib/routes'
import { fmtDate, plural } from '../../lib/format'
import { Button, Empty, ErrorBox, LoadingBlock, PageHeader, SyntheticBadge } from '../../components/ui/basics'
import { PriorityBadge, PriorityReasons, Sel } from '../../components/Priority'

function AppTable({ rows, showReasons = true }: { rows: any[]; showReasons?: boolean }) {
  const nav = useNavigate()
  return (
    <div className="panel overflow-x-auto">
      <table className="tbl">
        <thead><tr><th>Application</th><th>Institution</th><th>Type · year</th><th>Stage</th><th>Priority</th>{showReasons && <th>Why</th>}<th className="text-right">Open findings</th><th>Action required</th></tr></thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} className="row-link" onClick={() => nav(R.reviewer.app(a.id))}>
              <td className="whitespace-nowrap"><Link to={R.reviewer.app(a.id)} onClick={(e) => e.stopPropagation()} className="font-medium text-link hover:underline">{a.reference}</Link>{a.is_synthetic && <div><SyntheticBadge /></div>}</td>
              <td className="min-w-[180px]">{a.institution.name}</td>
              <td className="text-xs">{a.category.name}<div className="text-text-muted">{a.academic_year}</div></td>
              <td className="text-xs">{a.status_label}</td>
              <td><PriorityBadge p={a.priority} /></td>
              {showReasons && <td className="min-w-[220px]"><PriorityReasons p={a.priority} compact /></td>}
              <td className={clsx('text-right tabular-nums', a.outstanding ? 'font-semibold text-bad' : 'text-text-faint')}>{a.outstanding}</td>
              <td className="min-w-[200px] text-xs">{a.next_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function OfficerDashboard() {
  const q = useQuery({ queryKey: ['reviewer', 'dashboard'], queryFn: () => api('/reviewer/dashboard') })
  if (q.isLoading) return <><PageHeader title="Dashboard" /><LoadingBlock rows={8} /></>
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  const d = q.data
  return (
    <div>
      <PageHeader title="Dashboard" sub={`${plural(d.total, 'submitted application')} · validity checked against ${fmtDate(d.reference_date)}`} />
      <section aria-label="Applications by stage" className="panel mb-6 overflow-x-auto">
        <ul className="grid min-w-[720px] grid-cols-6">
          {d.stages.map((s: any) => (
            <li key={s.key} className="border-r border-line last:border-r-0">
              <Link to={s.link} className="block px-4 py-3 hover:bg-sunk">
                <span className={clsx('block text-2xl font-semibold tabular-nums', s.value === 0 && 'text-text-faint')}>{s.value}</span>
                <span className="text-[12.5px] text-text-muted">{s.label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <div className="mb-2 flex items-end justify-between">
        <div>
          <h2 className="text-[15px] font-semibold">Priority queue</h2>
          <p className="text-xs text-text-muted">Review from the top. The score adds up the factors shown; it orders work and never approves or rejects.</p>
        </div>
        <Link to={R.reviewer.apps()} className="text-[13px] text-link hover:underline">All applications</Link>
      </div>
      {d.priority_queue.length === 0 ? <Empty title="Nothing waiting">All applications have a recorded decision.</Empty> : <AppTable rows={d.priority_queue} />}
    </div>
  )
}

export function OfficerApplications() {
  const [sp, setSp] = useSearchParams()
  const meta = useMeta()
  const [text, setText] = useState(sp.get('q') ?? '')
  useEffect(() => setText(sp.get('q') ?? ''), [sp])
  const params = Object.fromEntries(sp.entries())
  const q = useQuery({ queryKey: ['reviewer', 'apps', params], queryFn: () => api('/reviewer/applications', { params: { ...params, page_size: 25 } }), placeholderData: keepPreviousData })
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); if (k !== 'page') n.delete('page'); setSp(n) }
  const page = Number(sp.get('page') ?? 1)
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1
  const statuses = Object.entries(meta.data?.application_statuses ?? {}).filter(([k]) => k !== 'draft')
  const cur = sp.get('status') ?? ''
  return (
    <div>
      <PageHeader title="Applications" sub="Sorted by priority. Open an application to verify its documents."
        actions={<Button icon={<Download className="h-3.5 w-3.5" />} onClick={() => openFile(`/reviewer/applications/export.csv${qs({ status: sp.get('status'), q: sp.get('q') })}`, 'applications.csv').catch((e) => toast.error(errorMessage(e)))}>Export CSV</Button>} />
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <form className="min-w-[240px] flex-1" onSubmit={(e) => { e.preventDefault(); set('q', text.trim()) }}>
          <label className="field-label" htmlFor="q">Search</label>
          <div className="relative"><Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-text-faint" />
            <input id="q" className="input pl-8" placeholder="Application ID, institution or permanent ID" value={text} onChange={(e) => setText(e.target.value)} /></div>
        </form>
        <Sel id="st" label="Stage" value={cur} onChange={(v) => set('status', v)}
          options={[['', 'All stages'], ...(cur && !statuses.some(([k]) => k === cur) ? [[cur, 'Selected stages'] as [string, string]] : []), ...statuses]} />
        {(sp.get('q') || sp.get('status') || sp.get('has')) && <Button variant="ghost" onClick={() => setSp(new URLSearchParams())}>Clear filters</Button>}
      </div>
      {q.isLoading ? <LoadingBlock rows={8} /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.items.length === 0 ? (
        <Empty title="No applications match">Clear the search or stage filter.</Empty>
      ) : (
        <>
          <AppTable rows={q.data.items} />
          <div className="mt-2 flex items-center justify-between text-xs text-text-muted">
            <span>{q.data.total} application(s)</span>
            <span className="flex gap-2"><Button size="sm" disabled={page <= 1} onClick={() => set('page', String(page - 1))}>Previous</Button><Button size="sm" disabled={page >= pages} onClick={() => set('page', String(page + 1))}>Next</Button></span>
          </div>
        </>
      )}
    </div>
  )
}

export function OfficerNotices() {
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['reviewer', 'notices'], queryFn: () => api('/reviewer/notices') })
  return (
    <div>
      <PageHeader title="Notices" sub="Deficiency notices sent to institutions, their delivery and responses." />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.length === 0 ? (
        <Empty title="No notices sent yet">Create a deficiency notice from an application’s review page.</Empty>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Notice</th><th>Application</th><th>Institution</th><th>Respond by</th><th>Delivery</th><th>Response</th><th>Status</th></tr></thead>
            <tbody>{q.data.map((n: any) => (
              <tr key={n.id} className="row-link" onClick={() => nav(R.reviewer.app(n.application_id, 'notices'))}>
                <td className="whitespace-nowrap font-medium text-link">{n.reference}</td>
                <td className="text-xs">{n.application_reference}</td>
                <td>{n.institution}</td>
                <td className="whitespace-nowrap text-xs">{fmtDate(n.response_deadline)}</td>
                <td className="text-xs">{n.delivery.label}{n.delivery.seen_at && <div className="text-text-muted">{fmtDate(n.delivery.seen_at)}</div>}</td>
                <td className="text-xs tabular-nums">{n.responded_items} of {n.items} items</td>
                <td className="text-xs">{n.status_label}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}
