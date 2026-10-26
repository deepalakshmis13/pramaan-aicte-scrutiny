import { useLocation, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import clsx from 'clsx'
import { toast } from 'sonner'
import { Check, Download, Eye, FileDown, Play, Send, X } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { api, errorMessage, openFile, post } from '../../lib/api'
import { openPdf } from '../../lib/pdf'
import { R } from '../../lib/routes'
import { fieldLabel, fmtDate, fmtDateTime, plural } from '../../lib/format'
import { Button, Crumbs, Empty, ErrorBox, Field, KV, LoadingBlock, Modal, Mono, SyntheticBadge } from '../../components/ui/basics'
import { Certainty, ModeTag, Severity, StatusTag } from '../../components/ui/status'
import { PageView, type Highlight } from '../../components/PageView'
import { EvidenceMap } from '../../components/EvidenceMap'
import { PriorityBadge, PriorityReasons } from '../../components/Priority'

const AUTO: Record<string, [string, string]> = {
  missing: ['missing', 'Missing'], unreadable: ['inconclusive', 'Unreadable'], invalid: ['mismatch', 'Invalid'], expired: ['expired', 'Expired'],
  mismatch: ['mismatch', 'Mismatch'], incomplete: ['missing', 'Incomplete'], manual_verification_required: ['manual_review', 'Manual verification required'],
  external_unavailable: ['source_unavailable', 'External verification unavailable'], checks_passed: ['verified', 'Checks passed'], not_verified: ['pending', 'Not verified yet'],
}

function useInvalidate() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'reviewer' })
}

function Section({ id, title, aside, children }: { id: string; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-4 rounded-md border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {aside}
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}

/* ------------------------------------------------------------------ page */

export default function ApplicationReview() {
  const id = Number(useParams().applicationId)
  const loc = useLocation()
  const inv = useInvalidate()
  const [docOpen, setDocOpen] = useState<number | null>(null)
  const [focusFinding, setFocusFinding] = useState<number | null>(null)
  const q = useQuery({
    queryKey: ['reviewer', 'app', id], queryFn: () => api(`/reviewer/applications/${id}`), enabled: Number.isFinite(id),
    refetchInterval: (query) => ((query.state.data as any)?.active_run ? 1500 : false),
  })
  const wasRunning = useRef(false)
  useEffect(() => {
    const running = !!q.data?.active_run
    if (wasRunning.current && !running) { inv(); toast.success('Verification finished. Results are shown below.') }
    wasRunning.current = running
  }, [q.data?.active_run]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (q.data && loc.hash) document.getElementById(loc.hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [q.data?.id, loc.hash]) // eslint-disable-line react-hooks/exhaustive-deps

  const verify = useMutation({
    mutationFn: () => post(`/reviewer/applications/${id}/verify`),
    onSuccess: () => { toast.message('Verification started'); inv() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  if (q.isLoading) return <LoadingBlock rows={10} />
  if (q.isError) return <div className="space-y-3"><Crumbs items={[{ label: 'Applications', to: R.reviewer.apps() }, { label: `#${id}` }]} /><ErrorBox error={q.error} retry={q.refetch} /></div>
  const a = q.data
  const p = a.progress
  const pct = p.total ? Math.round((p.accepted / (p.total + p.missing_types)) * 100) : 0
  const running = !!a.active_run || verify.isPending
  const closed = ['decided'].includes(a.status)

  return (
    <div className="space-y-5">
      <Crumbs items={[{ label: 'Applications', to: R.reviewer.apps() }, { label: a.reference }]} />

      {/* 1. Summary */}
      <section className="rounded-md border border-line bg-surface">
        <div className="flex flex-wrap items-start justify-between gap-4 px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h1 className="text-[21px] font-semibold leading-tight">{a.institution.name}</h1>{a.is_synthetic && <SyntheticBadge />}</div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-text-muted">
              <span className="font-medium text-text">{a.reference}</span><span>{a.category.name}</span><span>AY {a.academic_year}</span>
              <span>Permanent ID {a.institution.permanent_id}</span><span>Submitted {fmtDate(a.submitted_at)}</span><span>Version {a.current_version}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-[11px] text-text-faint">Current stage</div>
            <div className="text-[14px] font-semibold">{a.status_label}</div>
          </div>
        </div>
        <div className="grid gap-px border-t border-line bg-line md:grid-cols-3">
          <div className="bg-surface px-5 py-3">
            <div className="text-[11px] text-text-faint">Next action</div>
            <div className="mt-0.5 text-[13.5px] font-medium">{a.next_action.officer}</div>
            <div className="mt-3">
              <Button variant="primary" icon={<Play className="h-3.5 w-3.5" />} busy={running} disabled={closed} onClick={() => verify.mutate()}>
                {running ? `Verifying… ${a.active_run?.stage ?? ''}` : 'Verify Application'}
              </Button>
              <p className="mt-1.5 text-[11.5px] text-text-muted">Runs the real checks: required documents, readability and OCR, field extraction, rules, duplicates and configured external sources.</p>
            </div>
          </div>
          <div className="bg-surface px-5 py-3">
            <div className="flex items-center justify-between"><span className="text-[11px] text-text-faint">Priority</span><PriorityBadge p={a.priority} /></div>
            <div className="mt-1.5"><PriorityReasons p={a.priority} /></div>
            <p className="mt-2 text-[11px] text-text-faint">Orders workload only. It never approves or rejects.</p>
          </div>
          <div className="bg-surface px-5 py-3">
            <div className="text-[11px] text-text-faint">Verification progress</div>
            <div className="mt-1 text-[13px]"><b>{p.accepted}</b> of {p.total} documents accepted{p.missing_types ? <>, <b className="text-bad">{p.missing_types}</b> required missing</> : ''}</div>
            <div className="mt-2 h-2 rounded bg-sunk" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><div className="h-2 rounded bg-ok" style={{ width: `${pct}%` }} /></div>
            <div className="mt-2 text-xs text-text-muted">{p.rejected} rejected · {p.pending} awaiting decision · {a.runs.length ? `last verified ${fmtDateTime(a.runs[0].finished_at)}` : 'not verified yet'}</div>
          </div>
        </div>
        <div className="border-t border-line px-5 py-2 text-xs text-text-muted">
          Declared: name “{a.declared.institution_name}” · permanent ID {a.declared.permanent_id} · approved intake {a.declared.approved_intake}
          <nav className="mt-1 flex flex-wrap gap-x-4" aria-label="Sections">
            {[['documents', 'Documents'], ['verification', 'Verification results'], ['notices', 'Notices'], ['decision', 'Decision'], ['history', 'History']].map(([k, l]) =>
              <a key={k} href={`#${k}`} className="text-link hover:underline">{l}</a>)}
          </nav>
        </div>
      </section>

      <DocumentsSection app={a} onOpen={setDocOpen} />
      <VerificationSection app={a} onOpenDoc={setDocOpen} focus={focusFinding} />
      <NoticesSection app={a} />
      <DecisionSection app={a} />
      <HistorySection app={a} onOpenDoc={setDocOpen} onFocusFinding={(f) => { setFocusFinding(f); document.getElementById('verification')?.scrollIntoView() }} />

      {docOpen != null && <DocumentDrawer app={a} documentId={docOpen} onClose={() => setDocOpen(null)} />}
    </div>
  )
}

/* ------------------------------------------------------------------ documents */

function DecisionCell({ d }: { d: any }) {
  if (d.review_status === 'accepted') return <span className="text-xs text-ok"><Check className="mr-1 inline h-3.5 w-3.5" />Accepted{d.manually_verified ? ' (manually verified)' : ''}<div className="text-text-muted">{d.reviewed_by} · {fmtDate(d.reviewed_at)}</div></span>
  if (d.review_status === 'rejected') return <span className="text-xs text-bad">Rejected<div className="max-w-[260px] text-text-muted">{d.review_note}</div></span>
  if (d.review_status === 'manual') return <span className="text-xs text-warn">Manual verification<div className="max-w-[260px] text-text-muted">{d.review_note}</div></span>
  return <span className="text-xs text-text-muted">Awaiting decision</span>
}

function ReviewDialog({ target, onClose }: { target: { doc: any; action: 'accept' | 'reject' | 'manual' } | null; onClose: () => void }) {
  const inv = useInvalidate()
  const [note, setNote] = useState('')
  useEffect(() => setNote(''), [target])
  const m = useMutation({
    mutationFn: () => post(`/reviewer/document-versions/${target!.doc.version_id}/review`, { action: target!.action, note }),
    onSuccess: (r: any) => {
      toast.success({ accept: 'Document accepted', reject: 'Document rejected — it can now be included in a deficiency notice', manual: 'Marked for manual verification' }[target!.action] +
        (r.resolved_findings?.length ? ` (${r.resolved_findings.length} finding(s) resolved)` : ''))
      inv(); onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  if (!target) return null
  const { doc, action } = target
  const needsNote = action !== 'accept' || doc.open_findings.length > 0
  const min = action === 'reject' ? 15 : action === 'manual' ? 5 : doc.open_findings.length ? 10 : 0
  const copy = {
    accept: { t: `Accept ${doc.title}`, d: doc.open_findings.length ? `${doc.open_findings.length} open finding(s) refer to this document. Explain why you accept it; those findings will be marked resolved.` : 'The automated checks raise no open issue for this document. Accepting it does not approve the application.' },
    reject: { t: `Reject ${doc.title}`, d: 'State exactly what is wrong. The reason is shown to the institution in the deficiency notice.' },
    manual: { t: `Manual verification — ${doc.title}`, d: 'Say what needs checking. Open the document, confirm or correct the extracted values, then accept or reject it.' },
  }[action]
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={copy.t} description={copy.d}>
      {needsNote && (<><label className="field-label" htmlFor="rn">{action === 'reject' ? 'Reason for rejection' : 'Note'}</label>
        <textarea id="rn" className="input min-h-[90px]" value={note} onChange={(e) => setNote(e.target.value)} />
        <p className="mt-1 text-xs text-text-faint">At least {min} characters.</p></>)}
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant={action === 'reject' ? 'danger' : 'primary'} busy={m.isPending} disabled={note.trim().length < min} onClick={() => m.mutate()}>
          {{ accept: 'Accept document', reject: 'Reject document', manual: 'Mark for manual verification' }[action]}
        </Button>
      </div>
    </Modal>
  )
}

function DocActions({ d, app, onOpen, onReview }: { d: any; app: any; onOpen: () => void; onReview: (a: 'accept' | 'reject' | 'manual') => void }) {
  const locked = ['awaiting_decision', 'decided'].includes(app.status)
  return (
    <div className="flex flex-nowrap justify-end gap-1">
      <Button size="sm" variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={onOpen}>Open</Button>
      {!locked && d.review_status !== 'accepted' && <Button size="sm" onClick={() => onReview('accept')}>Accept</Button>}
      {!locked && d.review_status !== 'rejected' && <Button size="sm" onClick={() => onReview('reject')}>Reject</Button>}
      {!locked && d.review_status === 'pending' && <Button size="sm" variant="ghost" onClick={() => onReview('manual')}>Manual check</Button>}
    </div>
  )
}

function DocumentsSection({ app, onOpen }: { app: any; onOpen: (id: number) => void }) {
  const [target, setTarget] = useState<{ doc: any; action: 'accept' | 'reject' | 'manual' } | null>(null)
  return (
    <Section id="documents" title={`Documents (${app.documents.length})`} aside={<span className="text-xs text-text-muted">Accepting a document does not approve the application.</span>}>
      {app.missing.length > 0 && (
        <div className="mb-3 rounded border border-bad/30 bg-bad-soft px-4 py-2.5 text-[13px]">
          <b className="text-bad">Required documents not submitted:</b> {app.missing.map((m: any) => m.document_type_label).join(', ')}.
          <span className="text-text-muted"> Include them in a deficiency notice after verification.</span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="tbl">
          <thead><tr><th>Document</th><th>Uploaded</th><th>Automated check</th><th>Officer decision</th><th className="text-right">Actions</th></tr></thead>
          <tbody>
            {app.documents.map((d: any) => {
              const [st, label] = AUTO[d.auto_status] ?? ['pending', d.auto_status_label]
              return (
                <tr key={d.document_id}>
                  <td className="min-w-[200px]">
                    <button className="text-left font-medium text-link hover:underline" onClick={() => onOpen(d.document_id)}>{d.title}</button>
                    <div className="text-xs text-text-muted">{d.document_type_label} · version {d.version_no}{d.versions > 1 ? ` of ${d.versions}` : ''}{d.text_method === 'ocr' ? ` · OCR ${d.ocr_mean_confidence ?? ''}` : ''}</div>
                  </td>
                  <td className="whitespace-nowrap text-xs">{fmtDate(d.uploaded_at)}</td>
                  <td className="min-w-[200px]"><StatusTag state={st} label={label} size="sm" /><div className="mt-1 max-w-[320px] text-xs text-text-muted">{d.auto_status !== 'checks_passed' && d.auto_reason}</div></td>
                  <td className="min-w-[150px]"><DecisionCell d={d} /></td>
                  <td><DocActions d={d} app={app} onOpen={() => onOpen(d.document_id)} onReview={(action) => setTarget({ doc: d, action })} /></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ReviewDialog target={target} onClose={() => setTarget(null)} />
    </Section>
  )
}

function DocumentDrawer({ app, documentId, onClose }: { app: any; documentId: number; onClose: () => void }) {
  const inv = useInvalidate()
  const [version, setVersion] = useState<number | undefined>()
  const [hl, setHl] = useState<Highlight>(null)
  const [tab, setTab] = useState<'fields' | 'findings' | 'text' | 'history'>('fields')
  const [edit, setEdit] = useState<any>(null)
  const [target, setTarget] = useState<{ doc: any; action: 'accept' | 'reject' | 'manual' } | null>(null)
  const q = useQuery({ queryKey: ['reviewer', 'doc', app.id, documentId, version], queryFn: () => api(`/reviewer/applications/${app.id}/documents/${documentId}`, { params: { version } }) })
  const row = app.documents.find((d: any) => d.document_id === documentId)
  const confirm = useMutation({
    mutationFn: () => post(`/reviewer/fields/${edit.id}/confirm`, { value: edit.value, reason: 'Checked against the document' }),
    onSuccess: () => { toast.success('Value confirmed and recorded with your name'); setEdit(null); q.refetch(); inv() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const v = q.data?.selected_version
  return (
    <Modal open wide onOpenChange={(o) => !o && onClose()} title={row?.title ?? 'Document'} description={row ? `${row.document_type_label} · ${row.original_filename}` : undefined}>
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {row && <StatusTag state={AUTO[row.auto_status]?.[0]} label={AUTO[row.auto_status]?.[1]} size="sm" />}
            {row && <DecisionCell d={row} />}
            <span className="ml-auto flex items-center gap-2">
              {q.data.versions.length > 1 && (
                <select aria-label="Version" className="input w-auto" value={v.version_no} onChange={(e) => { setVersion(Number(e.target.value)); setHl(null) }}>
                  {q.data.versions.map((x: any) => <option key={x.id} value={x.version_no}>Version {x.version_no} (submission {x.submission_version})</option>)}
                </select>)}
              <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => openFile(`/reviewer/document-versions/${v.id}/file`, v.original_filename).catch((e) => toast.error(errorMessage(e)))}>Download original</Button>
            </span>
          </div>
          {row && row.auto_status !== 'checks_passed' && <p className="rounded bg-sunk px-3 py-2 text-[12.5px]"><b>Why: </b>{row.auto_reason}</p>}
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
            <div className="max-h-[62vh] overflow-auto rounded border border-line bg-[#d9dcd6] p-3">
              <PageView versionId={v.id} pages={v.mime_type === 'application/pdf' ? v.page_count : 1} highlight={hl} />
            </div>
            <div className="flex max-h-[62vh] flex-col rounded border border-line">
              <div role="tablist" className="flex gap-1 border-b border-line px-2 pt-1">
                {([['fields', `Extracted fields (${v.fields.length})`], ['findings', `Findings (${q.data.findings.filter((f: any) => f.is_issue).length})`], ['text', 'OCR / text'], ['history', 'Versions & decisions']] as const).map(([k, l]) => (
                  <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={clsx('-mb-px whitespace-nowrap border-b-2 px-2.5 py-2 text-[12px]', tab === k ? 'border-ink font-semibold' : 'border-transparent text-text-muted')}>{l}</button>
                ))}
              </div>
              <div className="flex-1 overflow-y-auto p-3 text-[12.5px]">
                {tab === 'fields' && (v.fields.length === 0 ? <p className="text-text-muted">No labelled values were extracted. Inspect the page image.</p> : (
                  <>
                    <p className="mb-2 text-xs text-text-muted">{v.text_method === 'ocr' ? `Read by OCR (mean confidence ${v.ocr_mean_confidence}).` : 'Read from the PDF text.'} Select a value to highlight it. Confirm or correct values you have checked.</p>
                    <table className="w-full"><tbody>
                      {v.fields.map((f: any) => (
                        <tr key={f.id} className="cursor-pointer border-b border-line hover:bg-[#fbf6e3]" onClick={() => f.bbox && setHl({ page: f.page, bbox: f.bbox, tone: 'field' })}>
                          <td className="w-[36%] py-1.5 pr-2 align-top text-text-muted">{fieldLabel(f.field_name)}{f.group_key && <div className="text-[10.5px] text-text-faint">{f.group_key}</div>}</td>
                          <td className="py-1.5 align-top">
                            {edit?.id === f.id ? (
                              <span className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                                <input aria-label="Confirmed value" className="input h-7" value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />
                                <Button size="sm" variant="primary" busy={confirm.isPending} onClick={() => confirm.mutate()}>Save</Button>
                                <Button size="sm" onClick={() => setEdit(null)}><X className="h-3.5 w-3.5" /></Button>
                              </span>
                            ) : (
                              <>
                                <div className={clsx(f.confirmed_value != null && 'font-medium')}>{f.effective_value}</div>
                                {f.confirmed_value != null && <div className="text-[11px] text-ok">Confirmed by officer (read as “{f.value}”)</div>}
                                {f.needs_confirmation && f.confirmed_value == null && <div className="text-[11px] text-warn">Low OCR confidence ({f.ocr_confidence ?? '—'}) — check before relying on it</div>}
                              </>
                            )}
                          </td>
                          <td className="w-16 py-1.5 text-right align-top">{edit?.id !== f.id && <button className="text-[11px] text-link hover:underline" onClick={(e) => { e.stopPropagation(); setEdit({ id: f.id, value: f.effective_value }) }}>{f.confirmed_value != null ? 'Edit' : 'Confirm'}</button>}</td>
                        </tr>
                      ))}
                    </tbody></table>
                  </>
                ))}
                {tab === 'findings' && (q.data.findings.filter((f: any) => f.is_issue).length === 0 ? <p className="text-text-muted">No issues reference this document.</p> : (
                  <ul className="space-y-2">{q.data.findings.filter((f: any) => f.is_issue).map((f: any) => {
                    const box = (f.evidence ?? []).find((e: any) => e.bbox && e.document_id === documentId)
                    return (
                      <li key={f.id} className="rounded border border-line p-2.5">
                        <div className="flex items-start justify-between gap-2"><b>{f.title}</b><StatusTag state={f.status} size="sm" /></div>
                        <p className="mt-1 text-text-muted">{f.reason}</p>
                        {f.limitations && <p className="mt-1 text-[11.5px] text-warn">{f.limitations}</p>}
                        {box && <button className="mt-1 text-xs text-link hover:underline" onClick={() => setHl({ page: box.page ?? 1, bbox: box.bbox, tone: f.category === 'anomaly' ? 'alert' : 'field' })}>Show on page</button>}
                      </li>
                    )
                  })}</ul>
                ))}
                {tab === 'text' && <pre className="whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed text-text-muted">{v.extracted_text || 'No text extracted.'}</pre>}
                {tab === 'history' && (
                  <div className="space-y-3">
                    <ul className="space-y-1">{q.data.versions.slice().reverse().map((x: any) => <li key={x.id}>Version {x.version_no} · {x.original_filename} · {fmtDateTime(x.uploaded_at)} <Mono className="text-text-faint">{x.sha256.slice(0, 12)}</Mono></li>)}</ul>
                    <div><b>Officer decisions</b>
                      {(row?.history ?? []).length === 0 ? <p className="text-text-muted">None yet.</p> :
                        <ul className="mt-1 space-y-1">{row.history.map((h: any, i: number) => <li key={i}><span className="capitalize">{h.action}</span> by {h.actor} · {fmtDateTime(h.at)}{h.note && <div className="text-text-muted">{h.note}</div>}</li>)}</ul>}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
          {row && v.id === row.version_id && !['awaiting_decision', 'decided'].includes(app.status) && (
            <div className="flex flex-wrap justify-end gap-2 border-t border-line pt-3">
              {row.review_status === 'pending' && <Button onClick={() => setTarget({ doc: row, action: 'manual' })}>Needs manual verification</Button>}
              {row.review_status !== 'rejected' && <Button onClick={() => setTarget({ doc: row, action: 'reject' })}>Reject</Button>}
              {row.review_status !== 'accepted' && <Button variant="primary" onClick={() => setTarget({ doc: row, action: 'accept' })}>{row.review_status === 'manual' ? 'Mark verified and accept' : 'Accept'}</Button>}
            </div>
          )}
        </div>
      )}
      <ReviewDialog target={target} onClose={() => setTarget(null)} />
    </Modal>
  )
}

/* ------------------------------------------------------------------ verification results */

function FindingRow({ f, onOpenDoc, open, onToggle }: { f: any; onOpenDoc: (id: number) => void; open: boolean; onToggle: () => void }) {
  const inv = useInvalidate()
  const [why, setWhy] = useState('')
  const dismiss = useMutation({
    mutationFn: () => post(`/reviewer/findings/${f.id}/review`, { action: 'dismiss', reason: why }),
    onSuccess: () => { toast.success('Finding dismissed with your reason'); inv() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const docEv = (f.evidence ?? []).find((e: any) => e.document_id)
  return (
    <li id={`finding-${f.id}`} className="border-b border-line last:border-0">
      <button className="flex w-full items-start gap-3 px-1 py-2.5 text-left hover:bg-sunk/60" aria-expanded={open} onClick={onToggle}>
        <StatusTag state={f.status} size="sm" />
        <span className="min-w-0 flex-1"><span className="text-[13px] font-medium">{f.title}</span>
          <span className="block text-xs text-text-muted">{f.code} · {f.category_label}{f.in_notice ? ' · in a notice' : ''}</span></span>
        {f.is_issue && <Severity level={f.severity} />}
      </button>
      {open && (
        <div className="mb-3 ml-1 space-y-2 rounded bg-sunk/50 p-3 text-[12.5px]">
          {(f.extracted_value || f.expected_value) && (
            <div className="grid gap-2 sm:grid-cols-2">
              <div><div className="text-[11px] text-text-faint">Found in the submission</div><div className="break-words font-medium">{f.extracted_value || '—'}</div></div>
              <div><div className="text-[11px] text-text-faint">Compared with / expected</div><div className="break-words font-medium">{f.expected_value || '—'}</div></div>
            </div>
          )}
          <p><b>Reason: </b>{f.reason}</p>
          {f.limitations && <p className="text-warn">{f.limitations}</p>}
          {f.source_check && <p className="flex flex-wrap items-center gap-2"><b>Source:</b> {f.source_check.source_name} <ModeTag mode={f.source_check.mode} /> <span className="text-text-muted">{f.source_check.explanation}</span></p>}
          <div className="flex flex-wrap items-center gap-3 text-xs text-text-muted">
            <Certainty value={f.certainty} />{f.rule && <span>Rule {f.rule.code} v{f.rule.version} — {f.rule.title}</span>}
            {docEv && <button className="text-link hover:underline" onClick={() => onOpenDoc(docEv.document_id)}>Open evidence document</button>}
          </div>
          {f.recommended_action && <p><b>Suggested action: </b>{f.recommended_action}</p>}
          {f.is_issue && !['resolved', 'verified'].includes(f.status) && f.review_state !== 'dismissed' && !f.in_notice && (
            <div className="flex flex-wrap items-end gap-2 border-t border-line pt-2">
              <div className="min-w-[220px] flex-1"><label className="field-label" htmlFor={`dw-${f.id}`}>Not an issue? Dismiss with a reason</label><input id={`dw-${f.id}`} className="input" value={why} onChange={(e) => setWhy(e.target.value)} /></div>
              <Button size="sm" disabled={why.trim().length < 3} busy={dismiss.isPending} onClick={() => dismiss.mutate()}>Dismiss</Button>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

function VerificationSection({ app, onOpenDoc, focus }: { app: any; onOpenDoc: (id: number) => void; focus: number | null }) {
  const [all, setAll] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [map, setMap] = useState(false)
  useEffect(() => { if (focus) setOpen(focus) }, [focus])
  const q = useQuery({ queryKey: ['reviewer', 'findings', app.id, all], queryFn: () => api(`/reviewer/applications/${app.id}/findings`, { params: { issues_only: !all } }), enabled: app.runs.length > 0 })
  const run = app.runs[0]
  const visible = (q.data ?? []).filter((f: any) => all || (!['verified', 'resolved'].includes(f.status) && f.review_state !== 'dismissed'))
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {}
    visible.forEach((f: any) => (g[f.category_label] ??= []).push(f))
    return g
  }, [visible])
  const unavailable = (q.data ?? []).filter((f: any) => f.status === 'source_unavailable').length
  return (
    <Section id="verification" title="Verification results"
      aside={<label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Show passing checks too</label>}>
      {!run ? <Empty title="Not verified yet">Click “Verify Application” above. Results appear here with the reason and evidence for each finding.</Empty> : (
        <>
          <p className="mb-3 text-[12.5px] text-text-muted">
            Run #{run.id} ({run.kind}) {run.status === 'completed' ? `finished ${fmtDateTime(run.finished_at)} · ${run.summary.checks} checks` : run.status === 'failed' ? `failed: ${run.error}` : run.status}.
            {unavailable > 0 && ` ${unavailable} external check(s) could not be completed — shown as “External verification unavailable”, not as failures.`}
          </p>
          {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : visible.length === 0 ? (
            <p className="rounded bg-ok-soft px-4 py-3 text-[13px] text-ok">No open findings. Review and accept the documents above.</p>
          ) : (
            <div className="space-y-4">
              {Object.entries(groups).map(([g, fs]) => (
                <div key={g}><h3 className="mb-1 text-xs font-semibold text-text-muted">{g} ({fs.length})</h3>
                  <ul>{fs.map((f) => <FindingRow key={f.id} f={f} onOpenDoc={onOpenDoc} open={open === f.id} onToggle={() => setOpen(open === f.id ? null : f.id)} />)}</ul></div>
              ))}
            </div>
          )}
          <div className="mt-4 border-t border-line pt-3">
            <button className="text-[13px] text-link hover:underline" aria-expanded={map} onClick={() => setMap((m) => !m)}>{map ? 'Hide' : 'Show'} how values link across documents</button>
            {map && <div className="mt-3"><EvidenceMap appId={app.id} onOpenDocument={onOpenDoc} onOpenFinding={(fid) => setOpen(fid)} /></div>}
          </div>
        </>
      )}
    </Section>
  )
}

/* ------------------------------------------------------------------ notices */

function NoticeForm({ app, onClose }: { app: any; onClose: () => void }) {
  const inv = useInvalidate()
  const q = useQuery({ queryKey: ['reviewer', 'candidates', app.id], queryFn: () => api(`/reviewer/notice-candidates/${app.id}`) })
  const [items, setItems] = useState<Record<number, any>>({})
  const [deadline, setDeadline] = useState('')
  const [cover, setCover] = useState('')
  const [step, setStep] = useState<'edit' | 'review'>('edit')
  useEffect(() => {
    if (q.data) {
      setDeadline(q.data.default_deadline)
      setItems(Object.fromEntries(q.data.items.map((c: any) => [c.finding_id, { on: ['rejected', 'missing', 'expired', 'mismatch'].includes(c.status), title: c.suggested_title, description: c.suggested_description, corrective_action: c.suggested_action, c }])))
    }
  }, [q.data])
  const chosen = Object.entries(items).filter(([, v]) => v.on)
  const send = useMutation({
    mutationFn: () => post(`/reviewer/applications/${app.id}/notices`, {
      response_deadline: deadline, cover_note: cover,
      items: chosen.map(([fid, v]) => ({ finding_id: Number(fid), title: v.title, description: v.description, corrective_action: v.corrective_action })),
    }),
    onSuccess: (r: any) => {
      if (r.status !== 'issued' || r.institution_id !== app.institution.id) { toast.error('The server did not confirm delivery of the notice.'); return }
      toast.success(`Notice ${r.reference} sent to ${r.institution}. ${r.delivery.label}.`)
      inv(); onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Modal open wide onOpenChange={(o) => !o && onClose()} title={step === 'edit' ? 'Create deficiency notice' : 'Review and send'}
      description={step === 'edit' ? 'Choose the findings to include and adjust the wording the institution will read.' : `The notice will be sent to ${app.institution.name} and appear in their portal immediately.`}>
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} /> : q.data.items.length === 0 ? (
        <Empty title="Nothing to include">There are no open findings or rejected documents that are not already in a notice.</Empty>
      ) : step === 'edit' ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Related application"><div className="input bg-sunk">{app.reference} — {app.institution.name}</div></Field>
            <Field label="Response deadline" htmlFor="dl"><input id="dl" type="date" className="input" value={deadline} onChange={(e) => setDeadline(e.target.value)} /></Field>
          </div>
          <ul className="space-y-2">
            {Object.entries(items).map(([fid, v]) => (
              <li key={fid} className={clsx('rounded border p-3', v.on ? 'border-ink' : 'border-line')}>
                <label className="flex items-start gap-2 text-[13px]"><input type="checkbox" className="mt-0.5" checked={v.on} onChange={(e) => setItems({ ...items, [fid]: { ...v, on: e.target.checked } })} />
                  <span><b>{v.c.title}</b> <StatusTag state={v.c.status} size="sm" /><span className="block text-xs text-text-muted">{v.c.document}</span></span></label>
                {v.on && (
                  <div className="mt-2 space-y-2 pl-6">
                    <input aria-label="Deficiency" className="input font-medium" value={v.title} onChange={(e) => setItems({ ...items, [fid]: { ...v, title: e.target.value } })} />
                    <textarea aria-label="Reason and evidence" className="input min-h-[60px]" value={v.description} onChange={(e) => setItems({ ...items, [fid]: { ...v, description: e.target.value } })} />
                    <textarea aria-label="Required corrective action" className="input min-h-[40px]" value={v.corrective_action} onChange={(e) => setItems({ ...items, [fid]: { ...v, corrective_action: e.target.value } })} />
                  </div>
                )}
              </li>
            ))}
          </ul>
          <Field label="Note to the institution (optional)" htmlFor="cv"><textarea id="cv" className="input" value={cover} onChange={(e) => setCover(e.target.value)} /></Field>
          <div className="flex justify-end gap-2"><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!chosen.length || !deadline} onClick={() => setStep('review')}>Review notice ({chosen.length})</Button></div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="rounded border border-line bg-white p-4">
            <div className="doc-paper text-[17px] font-semibold">Deficiency / Clarification Notice</div>
            <div className="text-xs text-text-muted">{app.reference} · {app.institution.name} · respond by {fmtDate(deadline)}</div>
            {cover && <p className="doc-paper mt-3 text-[14px]">{cover}</p>}
            <ol className="mt-3 space-y-3">{chosen.map(([fid, v], i) => (
              <li key={fid} className="border-t border-line pt-2 text-[13px]"><b>{i + 1}. {v.title}</b><p className="doc-paper text-[14px]">{v.description}</p><p><b>Action required: </b>{v.corrective_action}</p><p className="text-xs text-text-muted">Document: {v.c.document}</p></li>
            ))}</ol>
          </div>
          <div className="flex justify-end gap-2"><Button onClick={() => setStep('edit')}>Back to edit</Button>
            <Button variant="primary" icon={<Send className="h-3.5 w-3.5" />} busy={send.isPending} onClick={() => send.mutate()}>Send Notice</Button></div>
        </div>
      )}
    </Modal>
  )
}

function NoticesSection({ app }: { app: any }) {
  const inv = useInvalidate()
  const [form, setForm] = useState(false)
  const [outcome, setOutcome] = useState<{ item: any; outcome: string } | null>(null)
  const [note, setNote] = useState('')
  const q = useQuery({ queryKey: ['reviewer', 'responses', app.id], queryFn: () => api(`/reviewer/applications/${app.id}/responses`) })
  const rec = useMutation({
    mutationFn: () => post(`/reviewer/notice-items/${outcome!.item.id}/outcome`, { outcome: outcome!.outcome, note }),
    onSuccess: () => { toast.success('Outcome recorded'); setOutcome(null); setNote(''); inv() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const canCreate = ['under_scrutiny', 'response_received'].includes(app.status) && !app.notices.some((n: any) => n.status === 'issued')
  return (
    <Section id="notices" title="Deficiency notices and responses"
      aside={canCreate && <Button variant="primary" icon={<Send className="h-3.5 w-3.5" />} onClick={() => setForm(true)}>Create Deficiency Notice</Button>}>
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.length === 0 ? (
        <p className="text-[13px] text-text-muted">No notice has been sent. After verifying, reject documents that need correction and create a notice for them and any missing items.</p>
      ) : (
        <div className="space-y-5">
          {q.data.map((n: any) => (
            <div key={n.id}>
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div><b>{n.reference}</b> <span className="text-[13px] text-text-muted">· {n.status_label} · sent {fmtDateTime(n.issued_at)} · respond by {fmtDate(n.response_deadline)}</span></div>
                {n.report_id && <Button size="sm" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => openPdf(`/reviewer/reports/${n.report_id}/download`, n.reference)}>Notice PDF</Button>}
              </div>
              <ol className="space-y-2">
                {n.items.map((it: any) => {
                  const resp = it.responses.filter((r: any) => r.status === 'submitted')
                  return (
                    <li key={it.id} className="rounded border border-line p-3 text-[13px]">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <b>{it.item_no}. {it.title}</b>
                        <span className="text-xs">Item: <b className="capitalize">{it.status.replace('_', ' ')}</b> · finding <StatusTag state={it.finding.status} size="sm" /></span>
                      </div>
                      <p className="mt-1 text-text-muted">{it.description}</p>
                      {resp.length > 0 ? resp.map((r: any) => (
                        <div key={r.id} className="mt-2 rounded border border-link/30 bg-[#f4f7fd] p-2.5">
                          <div className="text-xs text-text-muted">Institution response · {fmtDateTime(r.created_at)}</div>
                          <p>{r.response_text}</p>
                          {it.comparison && <p className="mt-1 text-xs">Corrected file: <b>{it.comparison.document_title}</b> {it.comparison.previous ? `version ${it.comparison.previous.version_no} → ${it.comparison.replacement.version_no}` : '(new document)'} — review it in the Documents section above.</p>}
                        </div>
                      )) : n.status === 'issued' && <p className="mt-1 text-xs text-text-faint">No response yet.</p>}
                      {n.status === 'responded' && !['resolved', 'not_resolved', 'escalated'].includes(it.status) && (
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Button size="sm" onClick={() => setOutcome({ item: it, outcome: 'resolved' })}>Mark resolved</Button>
                          <Button size="sm" onClick={() => setOutcome({ item: it, outcome: 'not_resolved' })}>Not resolved</Button>
                        </div>
                      )}
                    </li>
                  )
                })}
              </ol>
            </div>
          ))}
          {app.status === 'response_received' && <p className="text-[12.5px] text-text-muted">Corrected documents were re-verified automatically. Accept or reject them in the Documents section; accepting a corrected document resolves the items it answers.</p>}
        </div>
      )}
      {form && <NoticeForm app={app} onClose={() => setForm(false)} />}
      <Modal open={!!outcome} onOpenChange={(o) => !o && setOutcome(null)} title={`Mark item ${outcome?.outcome.replace('_', ' ')}`} description="Your note is kept in the record. The institution sees the item status.">
        <textarea aria-label="Note" className="input min-h-[80px]" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="mt-3 flex justify-end gap-2"><Button onClick={() => setOutcome(null)}>Cancel</Button><Button variant="primary" busy={rec.isPending} disabled={note.trim().length < 3} onClick={() => rec.mutate()}>Save</Button></div>
      </Modal>
    </Section>
  )
}

/* ------------------------------------------------------------------ decision */

const decisionSchema = z.object({
  outcome: z.string().min(1, 'Choose the decision'),
  reasons: z.string().trim().min(20, 'State the reasons (at least 20 characters)'),
  conditions: z.string().optional(),
  acknowledge_open_issues: z.boolean().optional(),
})

function DecisionSection({ app }: { app: any }) {
  const inv = useInvalidate()
  const show = ['under_scrutiny', 'response_received', 'awaiting_decision', 'decided'].includes(app.status)
  const ctx = useQuery({ queryKey: ['reviewer', 'decision', app.id], queryFn: () => api(`/reviewer/applications/${app.id}/decision-context`), enabled: ['awaiting_decision', 'decided'].includes(app.status) })
  const { register, handleSubmit, formState, watch } = useForm<z.infer<typeof decisionSchema>>({ resolver: zodResolver(decisionSchema), defaultValues: { outcome: '', reasons: '', conditions: '', acknowledge_open_issues: false } })
  const ready = useMutation({ mutationFn: () => post(`/reviewer/applications/${app.id}/ready-for-decision`), onSuccess: () => { toast.success('Moved to decision'); inv() }, onError: (e) => toast.error(errorMessage(e)) })
  const decide = useMutation({ mutationFn: (v: any) => post(`/reviewer/applications/${app.id}/decision`, v), onSuccess: () => { toast.success('Decision recorded'); inv() }, onError: (e) => toast.error(errorMessage(e)) })
  if (!show) return <Section id="decision" title="Decision"><p className="text-[13px] text-text-muted">Available once the application is under scrutiny.</p></Section>
  const allAccepted = app.progress.total > 0 && app.progress.accepted === app.progress.total && app.progress.missing_types === 0
  return (
    <Section id="decision" title="Decision">
      {['under_scrutiny', 'response_received'].includes(app.status) && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-text-muted">{allAccepted ? 'All documents are accepted. Move the application to decision when scrutiny is complete.' : 'Every document must be accepted (and no notice awaiting a response) before the application can move to decision.'}</p>
          <Button variant="primary" disabled={!allAccepted} busy={ready.isPending} onClick={() => ready.mutate()}>Move to decision</Button>
        </div>
      )}
      {ctx.data?.decisions?.map((x: any) => (
        <div key={x.id} className="rounded border border-ink p-4">
          <div className="text-xs text-text-muted">Recorded {fmtDateTime(x.decided_at)} by {x.decided_by.full_name}</div>
          <div className="text-[16px] font-semibold">{x.outcome_label}</div>
          <p className="mt-1 whitespace-pre-wrap text-[13px]">{x.reasons}</p>
          {x.conditions && <p className="text-[13px]"><b>Conditions:</b> {x.conditions}</p>}
          {x.report_id && <Button size="sm" className="mt-2" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => openPdf(`/reviewer/reports/${x.report_id}/download`, 'Decision record')}>Decision record PDF</Button>}
        </div>
      ))}
      {app.status === 'awaiting_decision' && ctx.data && (
        <form className="space-y-3" onSubmit={handleSubmit((v) => decide.mutate(v))} noValidate>
          <p className="text-[12.5px] text-text-muted">{ctx.data.notice}</p>
          {ctx.data.open_issues.length > 0 && <p className="text-[13px] text-warn">{plural(ctx.data.open_issues.length, 'finding')} still open.</p>}
          <Field label="Decision" error={formState.errors.outcome?.message}>
            <div className="grid gap-1 sm:grid-cols-2">{Object.entries(ctx.data.outcomes).map(([k, l]: any) => <label key={k} className="flex items-center gap-2 text-[13px]"><input type="radio" value={k} {...register('outcome')} />{l}</label>)}</div>
          </Field>
          <Field label="Reasons" htmlFor="dr" error={formState.errors.reasons?.message}><textarea id="dr" className="input min-h-[90px]" {...register('reasons')} /></Field>
          {watch('outcome') === 'approved_with_conditions' && <Field label="Conditions" htmlFor="dc"><textarea id="dc" className="input" {...register('conditions')} /></Field>}
          {ctx.data.open_issues.length > 0 && <label className="flex items-start gap-2 text-[12.5px]"><input type="checkbox" className="mt-0.5" {...register('acknowledge_open_issues')} />I have considered the open findings and record this decision with them open.</label>}
          <Button variant="primary" type="submit" busy={decide.isPending}>Record decision</Button>
        </form>
      )}
    </Section>
  )
}

/* ------------------------------------------------------------------ history */

function HistorySection({ app, onOpenDoc, onFocusFinding }: { app: any; onOpenDoc: (id: number) => void; onFocusFinding: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const inv = useInvalidate()
  const pp = useQuery({ queryKey: ['reviewer', 'passport', app.id], queryFn: () => api(`/reviewer/applications/${app.id}/passport`), enabled: open })
  const notes = useQuery({ queryKey: ['reviewer', 'notes', app.id], queryFn: () => api(`/reviewer/applications/${app.id}/notes`), enabled: open })
  const reports = useQuery({ queryKey: ['reviewer', 'reports', app.id], queryFn: () => api(`/reviewer/applications/${app.id}/reports`), enabled: open })
  const add = useMutation({ mutationFn: () => post(`/reviewer/applications/${app.id}/notes`, { body: note }), onSuccess: () => { setNote(''); notes.refetch(); toast.success('Note saved') }, onError: (e) => toast.error(errorMessage(e)) })
  const gen = useMutation({ mutationFn: () => post(`/reviewer/applications/${app.id}/reports/internal`), onSuccess: (r: any) => { inv(); openPdf(`/reviewer/reports/${r.id}/download`, r.reference) }, onError: (e) => toast.error(errorMessage(e)) })
  const go = (link?: string | null) => {
    if (!link) return
    const m = link.match(/documents\/(\d+)/); if (m) return onOpenDoc(Number(m[1]))
    const f = link.match(/findings\/(\d+)/); if (f) return onFocusFinding(Number(f[1]))
  }
  return (
    <Section id="history" title="History, notes and reports" aside={<Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Show'}</Button>}>
      {!open ? (
        <p className="text-[13px] text-text-muted">Submissions: {app.submissions.map((s: any) => `version ${s.version} (${fmtDate(s.submitted_at)})`).join(', ')}. Open to see every verification run, source check, officer action, note and generated PDF.</p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div>
            <h3 className="mb-2 text-xs font-semibold text-text-muted">Verification history (passport)</h3>
            {pp.isLoading ? <LoadingBlock /> : pp.isError ? <ErrorBox error={pp.error} /> : (
              <ol className="max-h-[480px] overflow-y-auto pr-1">
                {pp.data.events.map((e: any, i: number) => (
                  <li key={i} className="grid grid-cols-[118px_1fr] gap-3 border-b border-line py-2 text-[12.5px]">
                    <span className="text-xs text-text-muted">{fmtDateTime(e.at)}</span>
                    <span className="min-w-0"><button className="text-left font-medium hover:text-link" onClick={() => go(e.link)}>{e.title}</button>
                      {e.detail && <span className="block break-words text-text-muted">{e.detail}</span>}<span className="text-[11px] text-text-faint">{e.actor}</span></span>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="space-y-5">
            <div>
              <h3 className="mb-2 text-xs font-semibold text-text-muted">Internal notes (never shown to the institution)</h3>
              <textarea aria-label="New note" className="input min-h-[60px]" value={note} onChange={(e) => setNote(e.target.value)} />
              <div className="mt-1 flex justify-end"><Button size="sm" disabled={note.trim().length < 2} busy={add.isPending} onClick={() => add.mutate()}>Save note</Button></div>
              <ul className="mt-2 space-y-2">{(notes.data ?? []).map((n: any) => <li key={n.id} className="text-[12.5px]">{n.body}<div className="text-[11px] text-text-faint">{n.author.full_name} · {fmtDateTime(n.created_at)}</div></li>)}</ul>
            </div>
            <div>
              <div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold text-text-muted">Reports</h3><Button size="sm" busy={gen.isPending} onClick={() => gen.mutate()}>Internal report PDF</Button></div>
              <ul className="space-y-1">{(reports.data ?? []).map((r: any) => (
                <li key={r.id} className="flex items-center justify-between gap-2 text-[12.5px]"><span>{r.reference} <span className="text-text-muted">· {fmtDate(r.generated_at)}</span></span>
                  <Button size="sm" variant="ghost" onClick={() => openPdf(`/reviewer/reports/${r.id}/download`, r.reference)}>Open</Button></li>))}</ul>
            </div>
            <KV rows={app.runs.slice(0, 5).map((r: any) => [`Run #${r.id}`, `${r.kind} · ${r.status} · ${fmtDateTime(r.finished_at)}`] as [string, string])} />
          </div>
        </div>
      )}
    </Section>
  )
}
