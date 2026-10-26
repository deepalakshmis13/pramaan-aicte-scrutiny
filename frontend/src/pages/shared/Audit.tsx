import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api } from '../../lib/api'
import { R } from '../../lib/routes'
import { fmtDateTime } from '../../lib/format'
import { Button, Empty, ErrorBox, LoadingBlock, Mono, PageHeader } from '../../components/ui/basics'
import { Sel } from '../../components/Priority'

const ACTIONS: [string, string][] = [['', 'All actions'], ['auth', 'Sign-in / sign-out'], ['document', 'Documents'], ['field', 'Field confirmations'], ['verification', 'Verification runs'],
  ['finding', 'Finding reviews'], ['notice', 'Notices'], ['institution', 'Institution actions'], ['decision', 'Decisions'], ['report', 'Reports'], ['rule', 'Rule changes'],
  ['admin', 'User administration'], ['source', 'Source configuration'], ['config', 'System configuration'], ['export', 'Exports']]

export default function Audit({ scope }: { scope: 'reviewer' | 'admin' }) {
  const [sp, setSp] = useSearchParams()
  const [open, setOpen] = useState<number | null>(null)
  const params = { action: sp.get('action') ?? undefined, q: sp.get('q') ?? undefined, application_id: sp.get('application_id') ?? undefined, actor: sp.get('actor') ?? undefined, page: sp.get('page') ?? 1, page_size: 40 }
  const q = useQuery({ queryKey: [scope, 'audit', params], queryFn: () => api(`/${scope}/audit`, { params }), placeholderData: keepPreviousData })
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); if (k !== 'page') n.delete('page'); setSp(n) }
  const page = Number(sp.get('page') ?? 1)
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1
  return (
    <div>
      <PageHeader title={scope === 'admin' ? 'Audit log' : 'Audit trail'} crumbs={[{ label: scope === 'admin' ? 'System' : 'Overview', to: scope === 'admin' ? R.admin.home : R.reviewer.home }, { label: 'Audit' }]}
        sub={scope === 'admin' ? 'All recorded events. Each event is chained to the previous one by SHA-256; System shows the chain check.' : 'Events for applications you can access.'} />
      <div className="panel mb-3 flex flex-wrap items-end gap-3 p-3">
        <Sel id="aa" label="Action" value={sp.get('action') ?? ''} onChange={(v) => set('action', v)} options={ACTIONS} />
        <div className="min-w-[200px] flex-1"><label className="field-label" htmlFor="aq">Search summaries</label>
          <input id="aq" className="input" defaultValue={sp.get('q') ?? ''} onKeyDown={(e) => e.key === 'Enter' && set('q', (e.target as HTMLInputElement).value)} /></div>
        {scope === 'admin' && <div><label className="field-label" htmlFor="ac">Actor</label><input id="ac" className="input" defaultValue={sp.get('actor') ?? ''} onKeyDown={(e) => e.key === 'Enter' && set('actor', (e.target as HTMLInputElement).value)} /></div>}
        {sp.get('application_id') && <Button size="sm" variant="ghost" onClick={() => set('application_id', '')}>Clear application filter</Button>}
      </div>
      {q.isLoading ? <LoadingBlock rows={10} /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.items.length === 0 ? <Empty title="No events match" /> : (
        <div className="panel overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Summary</th><th>Record</th><th>Chain</th></tr></thead>
            <tbody>
              {q.data.items.map((e: any) => (
                <Fragment key={e.id}>
                  <tr className="row-link" onClick={() => setOpen(open === e.id ? null : e.id)} aria-expanded={open === e.id}>
                    <td className="whitespace-nowrap text-xs">{fmtDateTime(e.at)}</td>
                    <td className="text-xs">{e.actor}<div className="text-text-faint">{e.actor_role}</div></td>
                    <td><Mono>{e.action}</Mono></td>
                    <td className="text-[12.5px]">{e.summary}</td>
                    <td className="whitespace-nowrap text-xs">
                      {e.application_reference ? (scope === 'reviewer' ? <Link onClick={(x) => x.stopPropagation()} to={R.reviewer.app(e.application_id)} className="text-link hover:underline">{e.application_reference}</Link> : e.application_reference) : `${e.entity_type} ${e.entity_id}`}
                    </td>
                    <td><Mono className="text-text-faint">{e.hash.slice(0, 10)}</Mono></td>
                  </tr>
                  {open === e.id && (
                    <tr><td colSpan={6} className="bg-sunk/50">
                      <div className="grid gap-2 text-xs sm:grid-cols-2">
                        <div><b>Event #{e.id}</b> · {e.entity_type} {e.entity_id}{e.ip && ` · from ${e.ip}`}<pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{JSON.stringify(e.details, null, 2)}</pre></div>
                        <div className="break-all font-mono text-[11px]">hash {e.hash}<br />prev {e.prev_hash || '(first event)'}</div>
                      </div>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-line px-3 py-2 text-xs text-text-muted">
            <span>{q.data.total} events · page {page} of {pages}</span>
            <span className="flex gap-2"><Button size="sm" disabled={page <= 1} onClick={() => set('page', String(page - 1))}>Previous</Button><Button size="sm" disabled={page >= pages} onClick={() => set('page', String(page + 1))}>Next</Button></span>
          </div>
        </div>
      )}
    </div>
  )
}
