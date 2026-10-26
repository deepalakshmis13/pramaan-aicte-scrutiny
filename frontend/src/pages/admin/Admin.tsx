import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import clsx from 'clsx'
import { toast } from 'sonner'
import { Plus } from 'lucide-react'
import { api, errorMessage, patch, post, del } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { Button, Empty, ErrorBox, Field, KV, LoadingBlock, Modal, Mono, PageHeader } from '../../components/ui/basics'
import { Glyph, ModeTag, StatusTag } from '../../components/ui/status'



/* ------------------------------------------------------------------ system */

export function AdminSystem() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['admin', 'system'], queryFn: () => api('/admin/system') })
  const [cfg, setCfg] = useState<Record<string, string>>({})
  const save = useMutation({
    mutationFn: (key: string) => patch('/admin/config', { key, value: cfg[key] ?? '' }),
    onSuccess: () => { toast.success('Configuration saved'); qc.invalidateQueries({ queryKey: ['admin', 'system'] }) },
    onError: (e) => toast.error(errorMessage(e)),
  })
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  const d = q.data
  return (
    <div>
      <PageHeader title="System status" sub={`Environment: ${d.environment}. Administrators manage configuration; application documents remain with scrutiny officers.`} />
      <div className="grid gap-5 lg:grid-cols-2">
        <section className="panel">
          <div className="panel-h"><h2 className="panel-t">Health checks</h2><Button size="sm" onClick={() => q.refetch()} busy={q.isFetching}>Re-check</Button></div>
          <ul>{d.checks.map((c: any) => (
            <li key={c.name} className="flex items-start gap-3 border-b border-line px-4 py-2.5 last:border-0">
              <span className={c.ok ? 'text-ok' : 'text-warn'}><Glyph state={c.ok ? 'verified' : 'manual_review'} /></span>
              <span className="w-40 shrink-0 text-[13px] font-medium">{c.name}</span><span className="text-[12.5px] text-text-muted">{c.detail}</span>
            </li>))}</ul>
        </section>
        <section className="panel p-4">
          <h2 className="panel-t">Audit chain integrity</h2>
          <p className={clsx('mt-2 text-[13px]', d.audit_chain.ok ? 'text-ok' : 'text-bad')}>{d.audit_chain.ok ? `Intact — ${d.audit_chain.checked} events verified in sequence.` : `Broken at event #${d.audit_chain.broken_at_event_id}.`}</p>
          <p className="mt-1 text-xs text-text-muted">Each event stores the SHA-256 of its content plus the previous event’s hash. This detects later edits to recorded events; it is an integrity check, not a guarantee against a database superuser.</p>
          <p className="mt-3 text-[13px]">{d.recent_activity} events in the last 7 days.</p>
        </section>
        <section className="panel">
          <div className="panel-h"><h2 className="panel-t">Configuration</h2></div>
          <ul>{Object.entries(d.config).map(([k, c]: any) => (
            <li key={k} className="border-b border-line px-4 py-3 last:border-0">
              <label className="field-label" htmlFor={k}>{c.description}</label>
              <div className="flex gap-2">
                <input id={k} className="input" type={k === 'expiry_reference_date' ? 'date' : 'number'} defaultValue={String(c.value ?? '')} onChange={(e) => setCfg({ ...cfg, [k]: e.target.value })} />
                <Button busy={save.isPending && save.variables === k} onClick={() => save.mutate(k)}>Save</Button>
              </div>
              <p className="mt-1 text-[11px] text-text-faint">Last changed {fmtDateTime(c.updated_at)}</p>
            </li>))}</ul>
        </section>
        <section className="panel">
          <div className="panel-h"><h2 className="panel-t">Processing failures</h2></div>
          {d.failed_runs.length === 0 && d.failed_documents.length === 0 ? <p className="px-4 py-3 text-[13px] text-text-muted">No failed runs or documents.</p> : (
            <ul className="text-[12.5px]">
              {d.failed_runs.map((r: any) => <li key={r.id} className="border-b border-line px-4 py-2">Run #{r.id} (application {r.application_id}): <span className="text-bad">{r.error}</span></li>)}
              {d.failed_documents.map((x: any) => <li key={x.id} className="border-b border-line px-4 py-2">{x.filename}: <span className="text-bad">{x.error}</span></li>)}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ users */

const userSchema = z.object({
  email: z.string().email('Enter a valid email'),
  full_name: z.string().min(2, 'Required'),
  designation: z.string().optional(),
  role: z.enum(['reviewer', 'institution', 'admin']),
  institution_id: z.string().optional(),
  password: z.string().min(10, 'At least 10 characters'),
})
const ROLE_LABEL: Record<string, string> = { reviewer: 'Scrutiny officer', institution: 'Institution', admin: 'Administrator' }

export function AdminUsers() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['admin', 'users'], queryFn: () => api('/admin/users') })
  const insts = useQuery({ queryKey: ['admin', 'insts'], queryFn: () => api('/admin/institutions') })
  const [open, setOpen] = useState(false)
  const [reset, setReset] = useState<any>(null)
  const [pw, setPw] = useState('')
  const f = useForm<z.infer<typeof userSchema>>({ resolver: zodResolver(userSchema), defaultValues: { role: 'reviewer' } })
  const role = f.watch('role')
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin', 'users'] })
  const create = useMutation({
    mutationFn: (v: any) => post('/admin/users', { ...v, institution_id: v.role === 'institution' ? Number(v.institution_id) : null }),
    onSuccess: () => { toast.success('User created'); setOpen(false); f.reset({ role: 'reviewer' }); refresh() },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const upd = useMutation({ mutationFn: ({ id, body }: any) => patch(`/admin/users/${id}`, body), onSuccess: () => { toast.success('User updated'); refresh(); setReset(null); setPw('') }, onError: (e) => toast.error(errorMessage(e)) })
  return (
    <div>
      <PageHeader title="Users" sub="Three roles: institution, scrutiny officer and administrator." actions={<Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>Add user</Button>} />
      {q.isLoading ? <LoadingBlock /> : q.isError ? <ErrorBox error={q.error} retry={q.refetch} /> : (
        <div className="panel overflow-x-auto"><table className="tbl">
          <thead><tr><th>Name</th><th>Role</th><th>Institution</th><th>Last sign-in</th><th>Status</th><th></th></tr></thead>
          <tbody>{q.data.map((u: any) => (
            <tr key={u.id} className={clsx(!u.is_active && 'text-text-faint')}>
              <td><div className="font-medium">{u.full_name}</div><div className="text-xs text-text-muted">{u.email} · {u.designation}</div></td>
              <td className="text-xs">{ROLE_LABEL[u.role]}</td><td className="text-xs">{u.institution_name ?? '—'}</td>
              <td className="whitespace-nowrap text-xs">{fmtDateTime(u.last_login_at)}</td>
              <td className="text-xs">{u.is_active ? 'Active' : 'Deactivated'}</td>
              <td className="whitespace-nowrap"><Button size="sm" variant="ghost" onClick={() => upd.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? 'Deactivate' : 'Reactivate'}</Button><Button size="sm" variant="ghost" onClick={() => setReset(u)}>Reset password</Button></td>
            </tr>))}</tbody>
        </table></div>
      )}
      <Modal open={open} onOpenChange={setOpen} title="Add user" description="Institution users only see their own institution’s records. Administrators manage configuration and cannot open application documents.">
        <form className="space-y-3" onSubmit={f.handleSubmit((v) => create.mutate(v))} noValidate>
          <Field label="Full name" htmlFor="un" error={f.formState.errors.full_name?.message}><input id="un" className="input" {...f.register('full_name')} /></Field>
          <Field label="Email" htmlFor="ue" error={f.formState.errors.email?.message}><input id="ue" className="input" {...f.register('email')} /></Field>
          <Field label="Designation" htmlFor="ud"><input id="ud" className="input" {...f.register('designation')} /></Field>
          <Field label="Role" htmlFor="ur"><select id="ur" className="input" {...f.register('role')}><option value="reviewer">Scrutiny officer</option><option value="institution">Institution representative</option><option value="admin">Administrator</option></select></Field>
          {role === 'institution' && <Field label="Institution" htmlFor="ui"><select id="ui" className="input" {...f.register('institution_id')}><option value="">Choose…</option>{(insts.data ?? []).map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></Field>}
          <Field label="Initial password" htmlFor="up" error={f.formState.errors.password?.message}><input id="up" type="password" className="input" autoComplete="new-password" {...f.register('password')} /></Field>
          <div className="flex justify-end gap-2"><Button type="button" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" busy={create.isPending}>Create user</Button></div>
        </form>
      </Modal>
      <Modal open={!!reset} onOpenChange={(o) => !o && setReset(null)} title={`Reset password — ${reset?.full_name ?? ''}`}>
        <label className="field-label" htmlFor="np">New password (10+ characters)</label><input id="np" type="password" className="input" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <div className="mt-4 flex justify-end gap-2"><Button onClick={() => setReset(null)}>Cancel</Button><Button variant="primary" disabled={pw.length < 10} busy={upd.isPending} onClick={() => upd.mutate({ id: reset.id, body: { new_password: pw } })}>Set password</Button></div>
      </Modal>
    </div>
  )
}

/* ------------------------------------------------------------------ rules */

function RuleForm({ initial, onSubmit, busy, isNew, checkTypes, onCancel }: any) {
  const [v, setV] = useState<any>(() => ({ ...initial, params: JSON.stringify(initial.params ?? {}, null, 0), categories: (initial.categories ?? []).join(',') }))
  const [err, setErr] = useState<string | null>(null)
  const s = (k: string) => (e: any) => setV({ ...v, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const submit = () => {
    let params
    try { params = JSON.parse(v.params || '{}') } catch { return setErr('Parameters must be valid JSON') }
    if ((v.change_note ?? '').trim().length < 5) return setErr('Describe the change (5+ characters)')
    setErr(null)
    onSubmit({ ...v, params, categories: v.categories ? v.categories.split(',').map((x: string) => x.trim()).filter(Boolean) : [], effective_to: v.effective_to || null })
  }
  return (
    <div className="space-y-3">
      {isNew && <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Code (e.g. FLD-003)" htmlFor="rc"><input id="rc" className="input" value={v.code ?? ''} onChange={s('code')} /></Field>
        <Field label="Title" htmlFor="rt"><input id="rt" className="input" value={v.title ?? ''} onChange={s('title')} /></Field>
        <Field label="Group" htmlFor="rg"><input id="rg" className="input" value={v.group ?? ''} onChange={s('group')} /></Field></div>}
      <Field label="Description" htmlFor="rd"><textarea id="rd" className="input min-h-[60px]" value={v.description} onChange={s('description')} /></Field>
      <Field label="Regulatory source reference" htmlFor="rs" hint="Cite the handbook clause or notification. Leave ‘confirmed’ unticked until verified against the current official text."><textarea id="rs" className="input min-h-[50px]" value={v.source_reference} onChange={s('source_reference')} /></Field>
      <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={!!v.source_verified} onChange={s('source_verified')} />Source confirmed against the current official text</label>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Check type" htmlFor="rct"><select id="rct" className="input" value={v.check_type} onChange={s('check_type')}>{checkTypes.map((c: string) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Severity" htmlFor="rsv"><select id="rsv" className="input" value={v.severity} onChange={s('severity')}><option>high</option><option>medium</option><option>low</option></select></Field>
        <Field label="Categories (blank = all)" htmlFor="rcat"><input id="rcat" className="input" value={v.categories} onChange={s('categories')} placeholder="EOA,INC" /></Field>
        <Field label="Effective from" htmlFor="ref"><input id="ref" type="date" className="input" value={v.effective_from} onChange={s('effective_from')} /></Field>
        <Field label="Effective to (optional)" htmlFor="ret"><input id="ret" type="date" className="input" value={v.effective_to ?? ''} onChange={s('effective_to')} /></Field>
        <Field label="Parameters (JSON)" htmlFor="rp"><input id="rp" className="input font-mono" value={v.params} onChange={s('params')} /></Field>
      </div>
      <Field label="Change note" htmlFor="rn"><input id="rn" className="input" value={v.change_note ?? ''} onChange={s('change_note')} /></Field>
      {err && <p role="alert" className="text-[13px] text-bad">{err}</p>}
      <div className="flex justify-end gap-2"><Button onClick={onCancel}>Cancel</Button><Button variant="primary" busy={busy} onClick={submit}>{isNew ? 'Create rule' : 'Save as new version'}</Button></div>
    </div>
  )
}

export function AdminRules() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['admin', 'rules'], queryFn: () => api('/admin/rules') })
  const [editing, setEditing] = useState<any>(null)
  const [creating, setCreating] = useState(false)
  const [hist, setHist] = useState<any>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin', 'rules'] })
  const version = useMutation({ mutationFn: (b: any) => post(`/admin/rules/${editing.id}/versions`, b), onSuccess: (r: any) => { toast.success(`Version ${r.version} saved; earlier versions retained`); setEditing(null); refresh() }, onError: (e) => toast.error(errorMessage(e)) })
  const create = useMutation({ mutationFn: (b: any) => post('/admin/rules', b), onSuccess: () => { toast.success('Rule created'); setCreating(false); refresh() }, onError: (e) => toast.error(errorMessage(e)) })
  const toggle = useMutation({ mutationFn: ({ id, active }: any) => post(`/admin/rules/${id}/active`, { active, reason: active ? 'Re-activated by administrator' : 'Deactivated by administrator' }), onSuccess: () => { toast.success('Rule updated'); refresh() }, onError: (e) => toast.error(errorMessage(e)) })
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  const groups: Record<string, any[]> = {}
  q.data.rules.forEach((r: any) => (groups[r.group] ??= []).push(r))
  return (
    <div>
      <PageHeader title="Regulatory rules" sub="Edits create a new version. Past findings stay linked to the version that produced them."
        actions={<Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setCreating(true)}>New rule</Button>} />
      <div className="space-y-5">{Object.entries(groups).map(([g, rules]) => (
        <section key={g} className="panel">
          <div className="panel-h"><h2 className="panel-t">{g}</h2></div>
          <ul>{rules.map((r: any) => {
            const c = r.current ?? r.versions[0]
            return (
              <li key={r.id} className="flex flex-wrap items-start gap-4 border-b border-line px-4 py-3 last:border-0">
                <div className="min-w-[260px] flex-1">
                  <div className="text-[13px] font-semibold">{r.code} — {r.title} <span className="font-normal text-text-muted">v{c.version}</span>{!r.current && <span className="ml-2 text-xs text-bad">inactive</span>}</div>
                  <p className="text-[12.5px] text-text-muted">{c.description}</p>
                  <p className="mt-1 text-[11.5px] text-text-faint">{c.check_type} · {c.severity} · {c.categories.length ? c.categories.join(', ') : 'all categories'} · from {c.effective_from}{c.effective_to ? ` to ${c.effective_to}` : ''} · params <Mono className="break-all">{JSON.stringify(c.params)}</Mono></p>
                  {!c.source_verified && <p className="text-[11.5px] text-warn">Source reference not confirmed</p>}
                </div>
                <div className="flex gap-1">
                  <Button size="sm" onClick={() => setEditing({ ...c, id: r.id, change_note: '' })}>New version</Button>
                  <Button size="sm" variant="ghost" onClick={() => setHist(r)}>History ({r.versions.length})</Button>
                  <Button size="sm" variant="ghost" onClick={() => toggle.mutate({ id: r.id, active: !r.current })}>{r.current ? 'Deactivate' : 'Activate'}</Button>
                </div>
              </li>)
          })}</ul>
        </section>))}</div>
      <Modal wide open={!!editing} onOpenChange={(o) => !o && setEditing(null)} title={`New version of ${editing?.code ?? ''}`}>
        {editing && <RuleForm initial={editing} checkTypes={q.data.check_types} busy={version.isPending} onCancel={() => setEditing(null)} onSubmit={(b: any) => version.mutate(b)} />}
      </Modal>
      <Modal wide open={creating} onOpenChange={setCreating} title="New rule">
        {creating && <RuleForm isNew initial={{ description: '', source_reference: '', check_type: 'required_fields', severity: 'medium', effective_from: new Date().toISOString().slice(0, 10), params: {}, categories: [] }} checkTypes={q.data.check_types} busy={create.isPending} onCancel={() => setCreating(false)} onSubmit={(b: any) => create.mutate(b)} />}
      </Modal>
      <Modal wide open={!!hist} onOpenChange={(o) => !o && setHist(null)} title={`Version history — ${hist?.code ?? ''}`}>
        <ol className="space-y-2">{hist?.versions.map((v: any) => (
          <li key={v.id} className="rounded border border-line p-3 text-[12.5px]"><div className="font-semibold">Version {v.version} {v.is_active ? <span className="text-ok">(current)</span> : <span className="text-text-muted">(superseded)</span>}</div>
            <div className="text-text-muted">{v.change_note} · created {fmtDateTime(v.created_at)}</div><div>{v.description}</div><Mono className="text-text-faint">{JSON.stringify(v.params)}</Mono></li>))}</ol>
      </Modal>
    </div>
  )
}

/* ------------------------------------------------------------------ categories */

export function AdminCategories() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['admin', 'cats'], queryFn: () => api('/admin/categories') })
  const [adding, setAdding] = useState<any>(null)
  const [item, setItem] = useState<any>({ document_type: '', label: '', mandatory: true, requires_validity: false, guidance: '' })
  const [newCat, setNewCat] = useState<any>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['admin', 'cats'] })
  const m = useMutation({ mutationFn: (fn: () => Promise<any>) => fn(), onSuccess: () => { toast.success('Saved'); refresh(); setAdding(null); setNewCat(null) }, onError: (e) => toast.error(errorMessage(e)) })
  if (q.isLoading) return <LoadingBlock rows={8} />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  return (
    <div>
      <PageHeader title="Application categories and checklists" sub="Checklist changes apply to verification runs from now on; earlier runs keep their recorded results."
        actions={<Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setNewCat({ code: '', name: '', description: '' })}>New category</Button>} />
      <div className="space-y-5">{q.data.categories.map((c: any) => (
        <section key={c.id} className="panel">
          <div className="panel-h"><div><h2 className="panel-t">{c.name} <span className="font-normal text-text-muted">({c.code})</span></h2><p className="text-xs text-text-muted">{c.description}</p></div>
            <Button size="sm" onClick={() => { setAdding(c); setItem({ document_type: '', label: '', mandatory: true, requires_validity: false, guidance: '' }) }}>Add checklist item</Button></div>
          <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>Item</th><th>Document type</th><th>Mandatory</th><th>Time-bound</th><th></th></tr></thead>
            <tbody>{c.checklist.map((i: any) => (
              <tr key={i.id}><td><div className="font-medium">{i.label}</div><div className="text-xs text-text-muted">{i.guidance}</div></td><td className="text-xs">{i.document_type_label}</td>
                <td><input type="checkbox" aria-label="Mandatory" checked={i.mandatory} onChange={(e) => m.mutate(() => patch(`/admin/checklist-items/${i.id}`, { mandatory: e.target.checked }))} /></td>
                <td><input type="checkbox" aria-label="Requires validity" checked={i.requires_validity} onChange={(e) => m.mutate(() => patch(`/admin/checklist-items/${i.id}`, { requires_validity: e.target.checked }))} /></td>
                <td><Button size="sm" variant="ghost" onClick={() => m.mutate(() => del(`/admin/checklist-items/${i.id}`))}>Remove</Button></td></tr>))}</tbody></table></div>
        </section>))}</div>
      <Modal open={!!adding} onOpenChange={(o) => !o && setAdding(null)} title={`Add checklist item — ${adding?.name ?? ''}`}>
        <div className="space-y-3">
          <Field label="Document type" htmlFor="cdt"><select id="cdt" className="input" value={item.document_type} onChange={(e) => setItem({ ...item, document_type: e.target.value, label: item.label || q.data.document_types[e.target.value] })}>
            <option value="">Choose…</option>{Object.entries(q.data.document_types).map(([k, l]: any) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Label" htmlFor="cl"><input id="cl" className="input" value={item.label} onChange={(e) => setItem({ ...item, label: e.target.value })} /></Field>
          <Field label="Guidance shown to institutions" htmlFor="cg"><input id="cg" className="input" value={item.guidance} onChange={(e) => setItem({ ...item, guidance: e.target.value })} /></Field>
          <div className="flex gap-4 text-[13px]"><label className="flex items-center gap-2"><input type="checkbox" checked={item.mandatory} onChange={(e) => setItem({ ...item, mandatory: e.target.checked })} />Mandatory</label><label className="flex items-center gap-2"><input type="checkbox" checked={item.requires_validity} onChange={(e) => setItem({ ...item, requires_validity: e.target.checked })} />Has a validity period</label></div>
          <div className="flex justify-end gap-2"><Button onClick={() => setAdding(null)}>Cancel</Button><Button variant="primary" disabled={!item.document_type || item.label.length < 3} busy={m.isPending} onClick={() => m.mutate(() => post(`/admin/categories/${adding.id}/checklist`, item))}>Add item</Button></div>
        </div>
      </Modal>
      <Modal open={!!newCat} onOpenChange={(o) => !o && setNewCat(null)} title="New application category">
        {newCat && <div className="space-y-3">
          <Field label="Code (capitals)" htmlFor="nc"><input id="nc" className="input" value={newCat.code} onChange={(e) => setNewCat({ ...newCat, code: e.target.value.toUpperCase() })} /></Field>
          <Field label="Name" htmlFor="nn"><input id="nn" className="input" value={newCat.name} onChange={(e) => setNewCat({ ...newCat, name: e.target.value })} /></Field>
          <Field label="Description" htmlFor="nd"><textarea id="nd" className="input" value={newCat.description} onChange={(e) => setNewCat({ ...newCat, description: e.target.value })} /></Field>
          <div className="flex justify-end gap-2"><Button onClick={() => setNewCat(null)}>Cancel</Button><Button variant="primary" busy={m.isPending} onClick={() => m.mutate(() => post('/admin/categories', newCat))}>Create category</Button></div>
        </div>}
      </Modal>
    </div>
  )
}

/* ------------------------------------------------------------------ sources */

export function AdminSources() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['admin', 'sources'], queryFn: () => api('/admin/sources') })
  const [test, setTest] = useState<Record<string, any>>({})
  const upd = useMutation({ mutationFn: ({ code, body }: any) => patch(`/admin/sources/${code}`, body), onSuccess: () => { toast.success('Source updated'); qc.invalidateQueries({ queryKey: ['admin', 'sources'] }) }, onError: (e) => toast.error(errorMessage(e)) })
  const run = useMutation({ mutationFn: (code: string) => post(`/admin/sources/${code}/test`), onSuccess: (r, code) => setTest({ ...test, [code]: r }), onError: (e) => toast.error(errorMessage(e)) })
  if (q.isLoading) return <LoadingBlock />
  if (q.isError) return <ErrorBox error={q.error} retry={q.refetch} />
  return (
    <div>
      <PageHeader title="Verification sources" sub="Credentials are read from server environment variables and are never shown or stored here." />
      <div className="space-y-4">{q.data.map((s: any) => (
        <section key={s.code} className="panel">
          <div className="panel-h flex-wrap"><div className="flex items-center gap-2"><h2 className="panel-t">{s.name}</h2><ModeTag mode={s.code === 'scopus' && !s.credentials_configured && s.mode === 'live' ? 'not_configured' : s.mode} /></div><span className="text-xs text-text-muted">{s.source_type} · {s.claim_types.join(', ')}</span></div>
          <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_minmax(260px,0.8fr)]">
            <div className="text-[12.5px]">
              <p>{s.notes}</p>
              <KV className="mt-2" rows={[['Endpoint', s.base_url || '—'], ['Credentials', s.requires_credentials ? (s.credentials_configured ? 'Configured on the server' : 'Not configured') : 'Not required'], ['Updated', fmtDateTime(s.updated_at)]]} />
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                <div><label className="field-label" htmlFor={`m-${s.code}`}>Mode</label>
                  <select id={`m-${s.code}`} className="input" value={s.mode} onChange={(e) => upd.mutate({ code: s.code, body: { mode: e.target.value } })}>
                    <option value="live">Live</option>{s.code === 'crossref' && <option value="simulated">Simulated (demo)</option>}<option value="disabled">Disabled</option></select></div>
                <div><label className="field-label" htmlFor={`r-${s.code}`}>Per minute</label><input id={`r-${s.code}`} type="number" className="input" defaultValue={s.rate_limit_per_minute} onBlur={(e) => Number(e.target.value) !== s.rate_limit_per_minute && upd.mutate({ code: s.code, body: { rate_limit_per_minute: Number(e.target.value) } })} /></div>
                <div><label className="field-label" htmlFor={`t-${s.code}`}>Timeout (s)</label><input id={`t-${s.code}`} type="number" className="input" defaultValue={s.timeout_seconds} onBlur={(e) => Number(e.target.value) !== s.timeout_seconds && upd.mutate({ code: s.code, body: { timeout_seconds: Number(e.target.value) } })} /></div>
              </div>
              <Button size="sm" busy={run.isPending && run.variables === s.code} onClick={() => run.mutate(s.code)}>Test connection</Button>
              {test[s.code] && <div className="rounded border border-line p-2.5 text-[12px]"><div className="flex items-center gap-2"><StatusTag state={test[s.code].status} size="sm" /><ModeTag mode={test[s.code].mode} />{test[s.code].http_status && <span>HTTP {test[s.code].http_status}</span>}</div><p className="mt-1 text-text-muted">{test[s.code].explanation}</p></div>}
            </div>
          </div>
        </section>))}</div>
      {q.data.length === 0 && <Empty title="No sources configured" />}
    </div>
  )
}


const SECTIONS: [string, string][] = [['system', 'System status'], ['checklists', 'Application types & checklists'], ['rules', 'Verification rules'], ['sources', 'External sources']]

export function AdminConfiguration() {
  const [sp, setSp] = useSearchParams()
  const cur = sp.get('section') ?? 'system'
  return (
    <div>
      <div role="tablist" aria-label="Configuration sections" className="mb-5 flex flex-wrap gap-1 border-b border-line">
        {SECTIONS.map(([k, l]) => (
          <button key={k} role="tab" aria-selected={cur === k} onClick={() => setSp({ section: k })}
            className={clsx('-mb-px border-b-2 px-3 py-2 text-[13px]', cur === k ? 'border-ink font-semibold' : 'border-transparent text-text-muted hover:text-text')}>{l}</button>
        ))}
      </div>
      {cur === 'system' && <AdminSystem />}
      {cur === 'checklists' && <AdminCategories />}
      {cur === 'rules' && <AdminRules />}
      {cur === 'sources' && <AdminSources />}
    </div>
  )
}
