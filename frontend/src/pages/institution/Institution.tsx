import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { toast } from 'sonner'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { FileDown, Plus, Upload } from 'lucide-react'
import { api, del, errorMessage, openFile, patch, post } from '../../lib/api'
import { openPdf } from '../../lib/pdf'
import { useAuth } from '../../lib/auth'
import { R } from '../../lib/routes'
import { fmtDate, fmtDateTime, plural } from '../../lib/format'
import { Button, Empty, ErrorBox, Field, LoadingBlock, Modal, PageHeader, SyntheticBadge } from '../../components/ui/basics'
import { Glyph } from '../../components/ui/status'

const STEPS: [string, string][] = [['draft', 'Draft'], ['submitted', 'Submitted'], ['under_scrutiny', 'Scrutiny'], ['notice_issued', 'Notice issued'],
  ['response_received', 'Response under review'], ['awaiting_decision', 'Awaiting decision'], ['decided', 'Decision']]
const stepIndex = (s: string) => (s === 'reverification' ? 4 : STEPS.findIndex(([k]) => k === s))

function Timeline({ status }: { status: string }) {
  const idx = stepIndex(status)
  return (
    <ol className="grid grid-cols-4 gap-1 sm:grid-cols-7" aria-label="Application progress">
      {STEPS.map(([k, l], i) => (
        <li key={k} aria-current={i === idx ? 'step' : undefined} className={clsx('rounded-sm px-2 py-1.5 text-[11.5px]', i < idx ? 'bg-ok-soft text-ok' : i === idx ? 'bg-ink text-white' : 'bg-sunk text-text-faint')}>
          <span className="block text-[10px] opacity-80">Step {i + 1}</span>{l}
        </li>
      ))}
    </ol>
  )
}

// Document types where several files are expected (one per faculty member / facility)
const MULTI = new Set(['qualification_certificate', 'infrastructure_photo'])

const DOC_TONE: Record<string, string> = { accepted: 'text-ok', rejected: 'text-bad', unreadable: 'text-bad', invalid: 'text-bad', uploaded: 'text-text', pending: 'text-text-muted', manual: 'text-warn' }

export function InstOverview() {
  const q = useQuery({ queryKey: ['inst', 'dashboard'], queryFn: () => api('/institution/dashboard') })
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  const d = q.data
  return (
    <div className="max-w-5xl">
      <PageHeader title={d.institution} sub={`AICTE permanent ID ${d.permanent_id}`}
        actions={<Link to={R.institution.newApp}><Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />}>New Application</Button></Link>} />
      {d.action_required.length > 0 ? (
        <section className="mb-6 rounded-md border-2 border-ink bg-surface">
          <h2 className="border-b border-line px-4 py-2.5 text-[14px] font-semibold">Action required</h2>
          <ul>{d.action_required.map((a: any) => (
            <li key={a.notice_id ?? `d${a.draft_application_id}`} className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 last:border-0">
              {a.notice_id ? (<>
                <div><div className="text-[13.5px] font-semibold">Respond to deficiency notice {a.reference}</div>
                  <div className="text-xs text-text-muted">{a.application_reference} · {plural(a.items, 'item')}, {a.items_without_response} still without a response</div></div>
                <div className="flex items-center gap-4">
                  <div className={clsx('text-right text-xs', a.days_left != null && a.days_left <= 3 ? 'font-semibold text-bad' : 'text-text-muted')}>Respond by {fmtDate(a.deadline)}<br />{a.days_left != null && (a.days_left >= 0 ? `${a.days_left} days left` : `${-a.days_left} days overdue`)}</div>
                  <Link to={R.institution.notice(a.notice_id)}><Button variant="primary">Open notice</Button></Link>
                </div></>) : (<>
                <div><div className="text-[13.5px] font-semibold">Finish and submit {a.reference}</div><div className="text-xs text-text-muted">Upload the required documents, then submit.</div></div>
                <Link to={R.institution.app(a.application_id)}><Button>Continue</Button></Link></>)}
            </li>))}</ul>
        </section>
      ) : <p className="mb-6 rounded-md border border-line bg-surface px-4 py-3 text-[13px] text-text-muted">Nothing needs your action right now.</p>}
      <h2 className="mb-2 text-[15px] font-semibold">Your applications</h2>
      {d.applications.length === 0 ? <Empty title="No applications yet" action={<Link to={R.institution.newApp}><Button variant="primary">New Application</Button></Link>}>Create an application to start.</Empty> : (
        <div className="space-y-3">{d.applications.map((a: any) => (
          <Link key={a.id} to={R.institution.app(a.id)} className="panel block p-4 hover:border-line-strong">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div><span className="font-semibold text-link">{a.reference}</span> <span className="text-[13px] text-text-muted">· {a.category} · AY {a.academic_year}</span> {a.is_synthetic && <SyntheticBadge />}</div>
              <span className="text-[13px] font-medium">{a.status_label}</span>
            </div>
            <Timeline status={a.status} />
            <p className="mt-2 text-[12.5px]"><span className="text-text-muted">Next: </span>{a.next_action}</p>
          </Link>))}</div>
      )}
    </div>
  )
}

export function InstApplications() {
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['inst', 'apps'], queryFn: () => api('/institution/applications') })
  return (
    <div className="max-w-5xl">
      <PageHeader title="My Applications" actions={<Link to={R.institution.newApp}><Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />}>New Application</Button></Link>} />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.length === 0 ? <Empty title="No applications yet">Use “New Application” to start one.</Empty> : (
        <div className="panel overflow-x-auto"><table className="tbl"><thead><tr><th>Application</th><th>Type</th><th>Academic year</th><th>Status</th><th>Next step</th><th>Version</th></tr></thead>
          <tbody>{q.data.map((a: any) => (
            <tr key={a.id} className="row-link" onClick={() => nav(R.institution.app(a.id))}><td><Link to={R.institution.app(a.id)} className="font-medium text-link hover:underline">{a.reference}</Link></td>
              <td>{a.category}</td><td>{a.academic_year}</td><td>{a.status_label}</td><td className="text-xs">{a.next_action}</td><td>v{a.current_version}</td></tr>
          ))}</tbody></table></div>
      )}
    </div>
  )
}

const appSchema = z.object({
  category_code: z.string().min(1, 'Choose the application type'),
  academic_year: z.string().regex(/^\d{4}-\d{2}$/, 'Use the form 2027-28'),
  declared_institution_name: z.string().trim().min(3, 'Enter the institution name'),
  declared_permanent_id: z.string().regex(/^\d-\d{6,12}$/, 'Format: 1-1234567890'),
  declared_approved_intake: z.coerce.number({ invalid_type_error: 'Enter the approved intake' }).int().min(1, 'Enter the approved intake').max(20000),
})
type AppForm = z.infer<typeof appSchema>

function DetailsForm({ initial, onSubmit, busy, submitLabel, categories, lockType }: { initial: Partial<AppForm>; onSubmit: (v: AppForm) => void; busy: boolean; submitLabel: string; categories: any[]; lockType?: boolean }) {
  const { register, handleSubmit, formState, watch } = useForm<AppForm>({ resolver: zodResolver(appSchema), defaultValues: initial as any })
  const cat = categories.find((c) => c.code === watch('category_code'))
  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Application type" htmlFor="ct" error={formState.errors.category_code?.message}>
          <select id="ct" className="input" disabled={lockType} {...register('category_code')}>
            <option value="">Choose…</option>{categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </Field>
        <Field label="Academic year" htmlFor="ay" error={formState.errors.academic_year?.message}><input id="ay" className="input" placeholder="2027-28" {...register('academic_year')} /></Field>
        <Field label="Institution name (as on your documents)" htmlFor="nm" error={formState.errors.declared_institution_name?.message}><input id="nm" className="input" {...register('declared_institution_name')} /></Field>
        <Field label="AICTE permanent ID" htmlFor="pid" error={formState.errors.declared_permanent_id?.message}><input id="pid" className="input" {...register('declared_permanent_id')} /></Field>
        <Field label="Total approved intake" htmlFor="in" error={formState.errors.declared_approved_intake?.message}><input id="in" type="number" className="input" {...register('declared_approved_intake')} /></Field>
      </div>
      {cat && !lockType && (
        <div className="rounded border border-line bg-sunk/40 p-3 text-[12.5px]">
          <b>{cat.name}</b> needs {cat.checklist.filter((i: any) => i.mandatory).length} required documents:
          <span className="text-text-muted"> {cat.checklist.filter((i: any) => i.mandatory).map((i: any) => i.label).join(', ')}.</span>
        </div>
      )}
      <Button variant="primary" type="submit" busy={busy}>{submitLabel}</Button>
    </form>
  )
}

export function NewApplication() {
  const { user } = useAuth()
  const nav = useNavigate()
  const qc = useQueryClient()
  const cats = useQuery({ queryKey: ['inst', 'categories'], queryFn: () => api('/institution/categories') })
  const dash = useQuery({ queryKey: ['inst', 'dashboard'], queryFn: () => api('/institution/dashboard') })
  const m = useMutation({
    mutationFn: (v: AppForm) => post('/institution/applications', v),
    onSuccess: (a: any) => { toast.success(`${a.reference} created. Upload the documents on the checklist.`); qc.invalidateQueries({ queryKey: ['inst'] }); nav(R.institution.app(a.id)) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  if (cats.isLoading || dash.isLoading) return <LoadingBlock />
  if (cats.isError) return <ErrorBox error={cats.error} retry={cats.refetch} />
  return (
    <div className="max-w-3xl">
      <PageHeader title="New application" crumbs={[{ label: 'My Applications', to: R.institution.apps }, { label: 'New application' }]}
        sub="Step 1 of 3: enter the details. Next you upload the documents on the checklist, then submit." />
      <div className="panel p-5">
        <DetailsForm categories={cats.data} busy={m.isPending} submitLabel="Create application and continue"
          initial={{ category_code: '', academic_year: '2027-28', declared_institution_name: user?.institution_name ?? '', declared_permanent_id: dash.data?.permanent_id ?? '' }}
          onSubmit={(v) => m.mutate(v)} />
      </div>
    </div>
  )
}

function UploadButton({ appId, type, replaceId, label, onDone }: { appId: number; type: string; replaceId?: number; label: string; onDone: (rows: any) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const m = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.set('document_type', type)
      fd.set('file', file)
      if (replaceId) fd.set('replace_document_id', String(replaceId))
      return api(`/institution/applications/${appId}/documents`, { method: 'POST', form: fd })
    },
    onSuccess: (rows) => { toast.success(replaceId ? 'Document replaced' : 'Document uploaded'); onDone(rows) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <>
      <input ref={ref} type="file" accept=".pdf,.png,.jpg,.jpeg" className="sr-only" aria-label={`${label} file`} data-doc-type={type}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) m.mutate(f); e.target.value = '' }} />
      <Button size="sm" variant={replaceId ? 'ghost' : 'secondary'} icon={!replaceId ? <Upload className="h-3.5 w-3.5" /> : undefined} busy={m.isPending} onClick={() => ref.current?.click()}>{label}</Button>
    </>
  )
}

function DraftEditor({ a, refetch }: { a: any; refetch: () => void }) {
  const qc = useQueryClient()
  const cats = useQuery({ queryKey: ['inst', 'categories'], queryFn: () => api('/institution/categories') })
  const [confirm, setConfirm] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const save = useMutation({ mutationFn: (v: AppForm) => patch(`/institution/applications/${a.id}`, v), onSuccess: () => { toast.success('Details saved'); refetch() }, onError: (e) => toast.error(errorMessage(e)) })
  const remove = useMutation({ mutationFn: (docId: number) => del(`/institution/applications/${a.id}/documents/${docId}`), onSuccess: () => { toast.success('Document removed'); refetch() }, onError: (e) => toast.error(errorMessage(e)) })
  const submit = useMutation({
    mutationFn: () => post(`/institution/applications/${a.id}/submit`),
    onSuccess: () => { setConfirm(false); toast.success(`${a.reference} submitted. It is now with the scrutiny officer.`); qc.invalidateQueries({ queryKey: ['inst'] }); refetch() },
    onError: (e: any) => { setConfirm(false); const msg = errorMessage(e); setErrors(msg.replace(/^The application cannot be submitted yet: /, '').split('; ')); toast.error('Fix the items listed before submitting') },
  })
  const docsByType = (t: string) => a.documents.filter((d: any) => d.document_type === t)
  const requiredMissing = a.checklist.filter((c: any) => c.mandatory && docsByType(c.document_type).length === 0).length
  return (
    <div className="space-y-5">
      <section className="panel p-5">
        <h2 className="mb-3 text-[15px] font-semibold">1. Application details</h2>
        {cats.data && <DetailsForm categories={cats.data} lockType busy={save.isPending} submitLabel="Save details"
          initial={{ category_code: a.category_code, academic_year: a.academic_year, declared_institution_name: a.declared.institution_name, declared_permanent_id: a.declared.permanent_id, declared_approved_intake: Number(a.declared.approved_intake) }}
          onSubmit={(v) => save.mutate(v)} />}
      </section>
      <section className="panel">
        <div className="panel-h"><h2 className="text-[15px] font-semibold">2. Documents for {a.category}</h2><span className="text-xs text-text-muted">{requiredMissing ? `${requiredMissing} required document(s) still missing` : 'All required documents uploaded'}</span></div>
        <ul>{a.checklist.map((c: any) => {
          const docs = docsByType(c.document_type)
          return (
            <li key={c.document_type} className="border-b border-line px-4 py-3 last:border-0" data-testid={`check-${c.document_type}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-2.5">
                  <span className={docs.length ? 'text-ok' : c.mandatory ? 'text-bad' : 'text-idle'}><Glyph state={docs.length ? 'verified' : c.mandatory ? 'missing' : 'pending'} /></span>
                  <div><div className="text-[13.5px] font-medium">{c.label} {c.mandatory ? <span className="text-xs font-normal text-bad">required</span> : <span className="text-xs font-normal text-text-muted">optional</span>}</div>
                    {c.guidance && <div className="text-xs text-text-muted">{c.guidance}</div>}</div>
                </div>
                {(docs.length === 0 || MULTI.has(c.document_type)) && <UploadButton appId={a.id} type={c.document_type} label={docs.length ? 'Add another' : 'Upload'} onDone={() => refetch()} />}
              </div>
              {docs.length > 0 && (
                <ul className="mt-2 space-y-1 pl-7">{docs.map((d: any) => (
                  <li key={d.document_id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-sunk/50 px-3 py-1.5 text-[12.5px]">
                    <span className="min-w-0"><span className="font-medium">{d.original_filename}</span> <span className={clsx('ml-2', DOC_TONE[d.status])}>{d.status_label}</span>
                      {d.status_reason && d.status !== 'uploaded' && <span className="block text-xs text-text-muted">{d.status_reason}</span>}</span>
                    <span className="flex gap-1">
                      <UploadButton appId={a.id} type={c.document_type} replaceId={d.document_id} label="Replace" onDone={() => refetch()} />
                      <Button size="sm" variant="ghost" busy={remove.isPending && remove.variables === d.document_id} onClick={() => remove.mutate(d.document_id)}>Remove</Button>
                    </span>
                  </li>))}</ul>
              )}
            </li>
          )
        })}</ul>
      </section>
      <section className="panel p-5">
        <h2 className="mb-2 text-[15px] font-semibold">3. Submit</h2>
        <p className="text-[13px] text-text-muted">After submission the application goes to the scrutiny officer and documents can only be changed in response to a notice.</p>
        {errors.length > 0 && <ul role="alert" className="mt-3 list-disc space-y-0.5 rounded border border-bad/30 bg-bad-soft py-2 pl-8 pr-3 text-[13px] text-bad">{errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        <Button className="mt-3" variant="primary" onClick={() => { setErrors([]); setConfirm(true) }}>Submit application</Button>
      </section>
      <Modal open={confirm} onOpenChange={setConfirm} title={`Submit ${a.reference}?`} description={`${a.documents.length} document(s) will be submitted for scrutiny. You cannot change them afterwards except in response to a deficiency notice.`}>
        <div className="flex justify-end gap-2"><Button onClick={() => setConfirm(false)}>Cancel</Button><Button variant="primary" busy={submit.isPending} onClick={() => submit.mutate()}>Submit application</Button></div>
      </Modal>
    </div>
  )
}

export function InstApplication() {
  const { applicationId } = useParams()
  const q = useQuery({ queryKey: ['inst', 'app', Number(applicationId)], queryFn: () => api(`/institution/applications/${applicationId}`) })
  const hist = useQuery({ queryKey: ['inst', 'history', Number(applicationId)], queryFn: () => api(`/institution/applications/${applicationId}/history`), enabled: !!q.data && q.data.status !== 'draft' })
  useEffect(() => { window.scrollTo(0, 0) }, [applicationId])
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  const a = q.data
  return (
    <div className="max-w-5xl">
      <PageHeader title={a.reference} crumbs={[{ label: 'My Applications', to: R.institution.apps }, { label: a.reference }]}
        sub={<>{a.category} · AY {a.academic_year} · version {a.current_version} {a.is_synthetic && <SyntheticBadge />}</>} />
      <div className="panel mb-5 p-4">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><span className="text-[14px] font-semibold">{a.status_label}</span><span className="text-[13px]"><span className="text-text-muted">Next: </span>{a.next_action}</span></div>
        <Timeline status={a.status} />
      </div>
      {a.status === 'draft' ? <DraftEditor a={a} refetch={q.refetch} /> : (
        <div className="space-y-5">
          {a.decision && (
            <section className="panel border-ink p-4">
              <div className="text-xs text-text-muted">Decision recorded {fmtDateTime(a.decision.decided_at)}</div>
              <div className="text-[16px] font-semibold">{a.decision.outcome_label}</div>
              {a.decision.conditions && <p className="mt-1 text-[13px]">Conditions: {a.decision.conditions}</p>}
              {a.decision.report_id && <Button size="sm" className="mt-2" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => openPdf(`/institution/reports/${a.decision.report_id}/download`, 'Decision record')}>Decision record</Button>}
            </section>
          )}
          {a.notices.length > 0 && (
            <section className="panel">
              <div className="panel-h"><h2 className="panel-t">Deficiency notices</h2></div>
              <ul>{a.notices.map((n: any) => (
                <li key={n.id} className="border-b border-line last:border-0"><Link to={R.institution.notice(n.id)} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 hover:bg-sunk">
                  <span><span className="text-[13px] font-medium text-link">{n.reference}</span> <span className="text-xs text-text-muted">· {plural(n.items, 'item')} · issued {fmtDate(n.issued_at)}</span></span>
                  <span className={clsx('text-xs', n.status === 'issued' ? 'font-semibold text-bad' : 'text-text-muted')}>{n.status === 'issued' ? `Respond by ${fmtDate(n.response_deadline)}` : n.status === 'responded' ? 'Response under review' : 'Closed'}</span>
                </Link></li>))}</ul>
            </section>
          )}
          <section className="panel">
            <div className="panel-h"><h2 className="panel-t">Documents ({a.documents.length})</h2></div>
            <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Document</th><th>Version</th><th>Uploaded</th><th>Status</th><th></th></tr></thead>
              <tbody>{a.documents.map((d: any) => (
                <tr key={d.document_id}><td>{d.title}<div className="text-xs text-text-muted">{d.original_filename}</div></td><td>v{d.version_no}</td><td className="whitespace-nowrap text-xs">{fmtDate(d.uploaded_at)}</td>
                  <td className={clsx('text-xs', DOC_TONE[d.status])}>{d.status_label}{d.status_reason && <div className="max-w-[320px] text-text-muted">{d.status_reason}</div>}</td>
                  <td><Button size="sm" variant="ghost" onClick={() => openFile(`/institution/document-versions/${d.version_id}/file`, d.original_filename).catch((e) => toast.error(errorMessage(e)))}>Download</Button></td></tr>
              ))}</tbody></table></div>
          </section>
          <section className="panel">
            <div className="panel-h"><h2 className="panel-t">Submission history</h2></div>
            {hist.isLoading ? <div className="p-4"><LoadingBlock rows={2} /></div> : (
              <ol className="divide-y divide-line">{(hist.data?.submissions ?? []).map((s: any) => (
                <li key={s.version} className="px-4 py-3 text-[13px]">
                  <div className="flex flex-wrap justify-between gap-2"><b>Version {s.version} — {s.kind === 'initial' ? 'original submission' : 'response to notice'}</b><span className="text-xs text-text-muted">{fmtDateTime(s.submitted_at)}</span></div>
                  {s.responses.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-text-muted">{s.responses.map((r: any, i: number) => <li key={i}>Item {r.item_no}: {r.text}{r.file ? ` (${r.file})` : ''} — {r.item_status.replace('_', ' ')}</li>)}</ul>}
                </li>))}</ol>
            )}
          </section>
        </div>
      )}
    </div>
  )
}

export function InstNotices() {
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['inst', 'notices'], queryFn: () => api('/institution/notices') })
  return (
    <div className="max-w-5xl">
      <PageHeader title="Notices" sub="Deficiency notices issued to your institution. Open one to respond." />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : q.data.length === 0 ? <Empty title="No notices">Notices issued to your institution appear here.</Empty> : (
        <div className="panel overflow-x-auto"><table className="tbl"><thead><tr><th>Notice</th><th>Application</th><th>Items</th><th>Issued</th><th>Respond by</th><th>Status</th></tr></thead>
          <tbody>{q.data.map((n: any) => (
            <tr key={n.id} className="row-link" onClick={() => nav(R.institution.notice(n.id))}><td><Link to={R.institution.notice(n.id)} className="font-medium text-link hover:underline">{n.reference}</Link></td><td>{n.application_reference}</td><td>{n.items}</td><td>{fmtDate(n.issued_at)}</td><td>{fmtDate(n.response_deadline)}</td><td>{n.status === 'issued' ? <span className="font-semibold text-bad">Response needed</span> : n.status}</td></tr>
          ))}</tbody></table></div>
      )}
    </div>
  )
}

function ItemResponse({ it, canRespond, onChanged }: { it: any; canRespond: boolean; onChanged: () => void }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const draft = it.responses.find((r: any) => r.status === 'draft')
  const submitted = it.responses.filter((r: any) => r.status === 'submitted')
  const save = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.set('response_text', text)
      if (file) fd.set('file', file)
      return api(`/institution/notice-items/${it.id}/response`, { method: 'POST', form: fd })
    },
    onSuccess: () => { toast.success(`Response to item ${it.item_no} saved as draft`); setText(''); setFile(null); onChanged() },
    onError: (e) => setErr(errorMessage(e)),
  })
  const discard = useMutation({ mutationFn: () => del(`/institution/responses/${draft.id}`), onSuccess: () => { toast.success('Draft discarded'); onChanged() }, onError: (e) => toast.error(errorMessage(e)) })
  const target = it.upload_target
  const needsDoc = !!it.needs_document
  return (
    <li className="panel" id={`item-${it.item_no}`}>
      <div className="flex items-start gap-3 border-b border-line px-4 py-3">
        <span className="font-serif text-[18px] font-semibold leading-none">{it.item_no}.</span>
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-semibold">{it.title}</div>
          <p className="mt-1 font-serif text-[14px] leading-relaxed">{it.description}</p>
          <p className="mt-2 text-[13px]"><span className="font-semibold">Action required: </span>{it.corrective_action}</p>
          <p className="mt-1 text-xs text-text-muted">Document: {it.document_reference}</p>
        </div>
        <span className={clsx('shrink-0 text-xs font-medium', it.status === 'resolved' ? 'text-ok' : it.status === 'open' ? (draft ? 'text-link' : 'text-bad') : 'text-text-muted')}>
          {it.status === 'open' ? (draft ? 'Draft ready' : 'Needs response') : it.status.replace('_', ' ')}
        </span>
      </div>
      <div className="px-4 py-3">
        {submitted.map((r: any) => (
          <div key={r.id} className="mb-2 rounded border border-line bg-sunk/40 p-2.5 text-[12.5px]"><div className="text-xs text-text-muted">Submitted {fmtDateTime(r.created_at)}</div>{r.response_text}{r.document_version && <div className="text-xs">File: {r.document_version.original_filename}</div>}</div>
        ))}
        {draft && (
          <div className="rounded border border-link/40 bg-[#f4f7fd] p-3 text-[12.5px]">
            <div className="flex items-center justify-between"><span className="font-semibold">Your draft response</span>{canRespond && <Button size="sm" variant="ghost" busy={discard.isPending} onClick={() => discard.mutate()}>Discard draft</Button>}</div>
            <p className="mt-1 whitespace-pre-wrap">{draft.response_text}</p>
            {draft.document_version && <p className="mt-1 text-xs">Attached: {draft.document_version.original_filename} — becomes {target.mode === 'replace' ? `a new version of “${target.label}”` : `a new “${target.label}” document`} when you submit.</p>}
          </div>
        )}
        {canRespond && !draft && (
          <div className="space-y-2">
            <label className="field-label" htmlFor={`rt-${it.id}`}>Your response or clarification</label>
            <textarea id={`rt-${it.id}`} className="input min-h-[70px]" value={text} onChange={(e) => setText(e.target.value)} />
            <label className="field-label" htmlFor={`rf-${it.id}`}>
              {target.mode === 'replace' ? `Upload a corrected version of “${target.label}”` : `Upload the required document (${target.label})`}{needsDoc ? '' : ' — optional'}
            </label>
            <input id={`rf-${it.id}`} type="file" accept=".pdf,.png,.jpg,.jpeg" className="block text-[13px]" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="text-xs text-text-faint">PDF, PNG or JPEG up to 15 MB. Earlier versions stay on record.</p>
            {err && <p role="alert" className="text-[13px] text-bad">{err}</p>}
            <Button icon={<Upload className="h-3.5 w-3.5" />} disabled={text.trim().length < 3} busy={save.isPending} onClick={() => { setErr(null); save.mutate() }}>Save response</Button>
          </div>
        )}
      </div>
    </li>
  )
}

export function InstNotice() {
  const { noticeId } = useParams()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [confirm, setConfirm] = useState(false)
  const q = useQuery({ queryKey: ['inst', 'notice', Number(noticeId)], queryFn: () => api(`/institution/notices/${noticeId}`) })
  const resubmit = useMutation({
    mutationFn: () => post(`/institution/notices/${noticeId}/resubmit`),
    onSuccess: () => { toast.success('Response submitted. Your corrected documents are being re-verified and the scrutiny officer has been notified.'); setConfirm(false); qc.invalidateQueries({ queryKey: ['inst'] }); nav(R.institution.app(q.data.application.id)) },
    onError: (e) => { setConfirm(false); toast.error(errorMessage(e)) },
  })
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  const n = q.data
  const ready = n.items.filter((i: any) => i.responses.some((r: any) => r.status === 'draft')).length
  return (
    <div className="max-w-4xl">
      <PageHeader title={`Deficiency notice ${n.reference}`} crumbs={[{ label: 'Notices', to: R.institution.notices }, { label: n.reference }]}
        sub={<>Application {n.application.reference} · issued {fmtDateTime(n.issued_at)} · {n.can_respond ? <b className="text-bad">respond by {fmtDate(n.response_deadline)}</b> : n.status_label}</>}
        actions={n.report_id && <Button icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => openPdf(`/institution/reports/${n.report_id}/download`, n.reference)}>Notice PDF</Button>} />
      {n.cover_note && <p className="mb-4 rounded border-l-2 border-ink bg-surface px-4 py-2 font-serif text-[14px]">{n.cover_note}</p>}
      {n.can_respond && (
        <div className="sticky top-0 z-10 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface px-4 py-3 shadow-lift">
          <div className="min-w-[200px] flex-1">
            <div className="text-[13px] font-semibold">{ready} of {n.items.length} items have a response</div>
            <div className="mt-1 h-1.5 rounded bg-sunk"><div className="h-1.5 rounded bg-ok" style={{ width: `${(ready / n.items.length) * 100}%` }} /></div>
          </div>
          <Button variant="primary" disabled={ready < n.items.length} onClick={() => setConfirm(true)}>Submit response</Button>
        </div>
      )}
      <ol className="space-y-3">{n.items.map((it: any) => <ItemResponse key={it.id} it={it} canRespond={n.can_respond} onChanged={() => q.refetch()} />)}</ol>
      <Modal open={confirm} onOpenChange={setConfirm} title="Submit your response?" description="Your responses and documents are submitted as a new version of the application. You cannot edit them afterwards; earlier versions remain on record. The documents are then re-verified.">
        <div className="flex justify-end gap-2"><Button onClick={() => setConfirm(false)}>Cancel</Button><Button variant="primary" busy={resubmit.isPending} onClick={() => resubmit.mutate()}>Submit response</Button></div>
      </Modal>
    </div>
  )
}

