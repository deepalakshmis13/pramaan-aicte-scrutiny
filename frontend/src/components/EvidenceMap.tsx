import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { Empty, ErrorBox, LoadingBlock } from './ui/basics'
import { StatusTag, stateInfo } from './ui/status'

const KIND_COL: Record<string, number> = { institution: 0, faculty: 0, publication: 0, room: 0, certificate: 0, form: 1, document: 1, source: 2, gap: 2 }
const KIND_LABEL: Record<string, string> = { institution: 'Institution', faculty: 'Faculty', publication: 'Publication', room: 'Facility', certificate: 'Certificate', form: 'Form', document: 'Document', source: 'External source', gap: 'Missing evidence' }
const EDGE_COLOR = (s: string) => (s === 'claim' || s === 'declared' ? '#9aa4b2' : ({ ok: '#0e7564', bad: '#b3261e', warn: '#a5650c', idle: '#7d8696', sim: '#5a5f95' } as any)[stateInfo(s).tone])

export function EvidenceMap({ appId, onOpenDocument, onOpenFinding }: { appId: number; onOpenDocument: (id: number) => void; onOpenFinding: (id: number) => void }) {
  const app = { id: appId }
  const q = useQuery({ queryKey: ['reviewer', 'graph', app.id], queryFn: () => api(`/reviewer/applications/${app.id}/evidence-graph`) })
  const [sel, setSel] = useState<string | null>(null)
  const layout = useMemo(() => {
    if (!q.data) return null
    const cols: any[][] = [[], [], []]
    const order = ['institution', 'faculty', 'publication', 'certificate', 'room', 'form', 'document', 'source', 'gap']
    ;[...q.data.nodes].sort((a: any, b: any) => order.indexOf(a.kind) - order.indexOf(b.kind)).forEach((n: any) => cols[KIND_COL[n.kind] ?? 1].push(n))
    const rowH = 46, W = 1000, colX = [10, 380, 750], nodeW = 240
    const pos: Record<string, { x: number; y: number }> = {}
    cols.forEach((c, ci) => c.forEach((n, i) => (pos[n.id] = { x: colX[ci], y: 30 + i * rowH })))
    const height = Math.max(...cols.map((c) => c.length)) * rowH + 40
    return { cols, pos, W, height, nodeW, rowH }
  }, [q.data])
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  if (!layout || q.data.edges.length === 0) return <Empty title="No relationships to show yet">Run verification to extract the fields this map is built from.</Empty>
  const { pos, W, height, nodeW } = layout
  const nodes: Record<string, any> = Object.fromEntries(q.data.nodes.map((n: any) => [n.id, n]))
  const related = sel ? q.data.edges.filter((e: any) => e.source === sel || e.target === sel) : []
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="panel overflow-x-auto">
        <div className="flex gap-6 border-b border-line px-4 py-2 text-xs text-text-muted"><span className="w-[37%]">Entities found in the documents</span><span className="w-[37%]">Documents</span><span>Sources and gaps</span></div>
        <svg viewBox={`0 0 ${W} ${height}`} className="min-w-[860px]" role="img" aria-label="Evidence map of entities, documents and sources">
          {q.data.edges.map((e: any, i: number) => {
            const a = pos[e.source], b = pos[e.target]
            if (!a || !b) return null
            const dim = sel && e.source !== sel && e.target !== sel
            const same = a.x === b.x
            const x1 = a.x + nodeW, y1 = a.y + 16, x2 = same ? b.x + nodeW : b.x, y2 = b.y + 16
            const d = same ? `M${x1},${y1} C${x1 + 70},${y1} ${x2 + 70},${y2} ${x2},${y2}` : `M${x1},${y1} C${x1 + 70},${y1} ${x2 - 70},${y2} ${x2},${y2}`
            return <path key={i} d={d} fill="none" stroke={EDGE_COLOR(e.state)} strokeWidth={e.state === 'claim' || e.state === 'declared' ? 1.1 : 2} strokeDasharray={e.state === 'claim' ? '4 3' : undefined} opacity={dim ? 0.12 : 0.9} />
          })}
          {q.data.nodes.map((n: any) => {
            const p = pos[n.id]
            if (!p) return null
            const active = sel === n.id
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} className="cursor-pointer" onClick={() => setSel(active ? null : n.id)} tabIndex={0} role="button" aria-pressed={active}
                onKeyDown={(ev) => (ev.key === 'Enter' || ev.key === ' ') && setSel(active ? null : n.id)}>
                <rect width={nodeW} height={32} rx={4} fill={n.kind === 'gap' ? '#f8e3e0' : n.kind === 'source' ? '#e8e8f3' : n.kind === 'document' || n.kind === 'form' ? '#ffffff' : '#eef1f6'} stroke={active ? '#0c1b33' : '#c4cac5'} strokeWidth={active ? 2 : 1} />
                <text x={10} y={14} fontSize={11.5} fontWeight={600} fill="#13203a">{n.label.length > 34 ? n.label.slice(0, 33) + '…' : n.label}</text>
                <text x={10} y={26} fontSize={9.5} fill="#556073">{KIND_LABEL[n.kind]} · {String(n.sub).slice(0, 34)}</text>
              </g>
            )
          })}
        </svg>
        <div className="flex flex-wrap gap-4 border-t border-line px-4 py-2 text-[11.5px] text-text-muted">
          <span className="inline-flex items-center gap-1.5"><svg width="22" height="6"><path d="M0 3h22" stroke="#9aa4b2" strokeDasharray="4 3" /></svg>stated in a document (not verified)</span>
          {['verified', 'mismatch', 'manual_review', 'source_unavailable'].map((s) => <span key={s} className="inline-flex items-center gap-1.5"><svg width="22" height="6"><path d="M0 3h22" stroke={EDGE_COLOR(s)} strokeWidth="2" /></svg>{stateInfo(s).label}</span>)}
        </div>
      </div>
      <aside className="panel p-4">
        {!sel ? (
          <div className="text-[12.5px] text-text-muted"><p className="font-semibold text-text">Select a node</p><p className="mt-1">See every value recorded for it and where it came from. {q.data.note}</p></div>
        ) : (
          <div>
            <div className="text-xs text-text-muted">{KIND_LABEL[nodes[sel].kind]}</div>
            <div className="text-[14px] font-semibold">{nodes[sel].label}</div>
            {nodes[sel].document_id && <button onClick={() => onOpenDocument(nodes[sel].document_id)} className="text-xs text-link hover:underline">Open document</button>}
            <ul className="mt-3 space-y-2">
              {related.map((e: any, i: number) => {
                const other = nodes[e.source === sel ? e.target : e.source]
                return (
                  <li key={i} className="rounded border border-line p-2 text-[12.5px]">
                    <div className="flex items-center justify-between gap-2"><span className="text-text-muted">{e.label}</span>{e.state !== 'claim' && e.state !== 'declared' && <StatusTag state={e.state} size="sm" />}</div>
                    <div className="font-medium">{e.value || '—'}</div>
                    <div className="text-xs text-text-muted">{other?.label}</div>
                    {e.finding_id && <button onClick={() => onOpenFinding(e.finding_id)} className="text-xs text-link hover:underline">Show finding</button>}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </aside>
    </div>
  )
}

