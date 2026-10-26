import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, errorMessage } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { homeFor } from '../../lib/routes'
import { Button, Field } from '../../components/ui/basics'
import { Wordmark } from '../../layouts/AppShell'

const schema = z.object({
  email: z.string().trim().email('Enter a valid email address'),
  password: z.string().min(1, 'Enter your password'),
})
type F = z.infer<typeof schema>

const DEMO = [
  { who: 'Scrutiny officer', email: 'anitha.raman@scrutiny.test', pw: 'Reviewer@2026' },
  { who: 'Institution — Aranya (notice to answer)', email: 'principal@aranya.test', pw: 'Institution@2026' },
  { who: 'Institution — Kaveri Valley (draft to finish)', email: 'principal@kaveri-valley.test', pw: 'Institution@2026' },
  { who: 'Administrator', email: 'admin@scrutiny.test', pw: 'Admin@2026' },
]

export default function Login() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const nav = useNavigate()
  const loc = useLocation() as any
  const [err, setErr] = useState<string | null>(null)
  const { register, handleSubmit, setValue, formState } = useForm<F>({ resolver: zodResolver(schema) })
  if (user) return <Navigate to={loc.state?.from ?? homeFor(user.role)} replace />

  const onSubmit = async (v: F) => {
    setErr(null)
    try {
      const r = await api('/auth/login', { method: 'POST', body: v })
      qc.setQueryData(['me'], { user: r.user, session_minutes: 480 })
      await qc.invalidateQueries({ queryKey: ['me'] })
      const from = loc.state?.from
      nav(from && from.startsWith(`/${r.user.role}`) ? from : homeFor(r.user.role), { replace: true })
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(420px,520px)]">
      <section className="relative hidden overflow-hidden bg-ink px-12 py-10 text-text-inverse lg:flex lg:flex-col">
        <Wordmark />
        <div className="mt-auto max-w-xl">
          <h1 className="font-serif text-[34px] font-semibold leading-[1.15] text-white">Post-submission scrutiny with every finding traced to its evidence.</h1>
          <p className="mt-4 max-w-md text-[14px] leading-relaxed text-[#b8c5da]">
            Officers examine submitted applications, compare claims across documents and external sources, and issue approved deficiency notices.
            The system organises evidence; decisions remain with authorised officials.
          </p>
          <ol className="mt-10 grid grid-cols-5 gap-px overflow-hidden rounded border border-ink-3 text-[11.5px]">
            {['Submit', 'Verify', 'Accept or reject', 'Notice & respond', 'Decide'].map((s, i) => (
              <li key={s} className="bg-ink-2 px-3 py-2.5">
                <span className="block text-[#7FD1C1]">{i + 1}</span>
                <span className="text-[#dbe3ef]">{s}</span>
              </li>
            ))}
          </ol>
        </div>
        <p className="mt-10 text-[11.5px] text-[#7f90ad]">Prototype. Synthetic institutions and documents only. Not an official AICTE system.</p>
      </section>
      <section className="flex flex-col justify-center px-6 py-10 sm:px-12">
        <div className="mb-8 lg:hidden"><Wordmark light={false} /></div>
        <h2 className="text-xl font-semibold">Sign in</h2>
        <p className="mt-1 text-[13px] text-text-muted">Use the account issued to you. Access is limited to your role.</p>
        <form onSubmit={handleSubmit(onSubmit)} className="mt-6 space-y-4" noValidate>
          <Field label="Email" htmlFor="email" error={formState.errors.email?.message}>
            <input id="email" type="email" autoComplete="username" className="input h-9" {...register('email')} />
          </Field>
          <Field label="Password" htmlFor="password" error={formState.errors.password?.message}>
            <input id="password" type="password" autoComplete="current-password" className="input h-9" {...register('password')} />
          </Field>
          {err && <p role="alert" className="rounded border border-bad/30 bg-bad-soft px-3 py-2 text-[13px] text-bad">{err}</p>}
          <Button type="submit" variant="primary" className="h-9 w-full" busy={formState.isSubmitting}>Sign in</Button>
        </form>
        <div className="mt-10 rounded-md border border-line bg-surface">
          <div className="border-b border-line px-3 py-2 text-xs font-semibold text-text-muted">Demo accounts (synthetic test data)</div>
          <ul>
            {DEMO.map((d) => (
              <li key={d.email} className="border-b border-line last:border-0">
                <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-[12.5px] hover:bg-sunk"
                  onClick={() => { setValue('email', d.email); setValue('password', d.pw) }}>
                  <span className="font-medium">{d.who}</span>
                  <span className="truncate text-text-muted">{d.email}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="px-3 py-2 text-[11.5px] text-text-faint">Selecting an account fills the form. Full list in the README.</p>
        </div>
      </section>
    </div>
  )
}
