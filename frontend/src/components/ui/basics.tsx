import clsx from 'clsx'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ChevronRight, Loader2 } from 'lucide-react'
import * as Dialog from '@radix-ui/react-dialog'

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'quiet'
  size?: 'sm' | 'md'
  busy?: boolean
  icon?: ReactNode
}

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = 'secondary', size = 'md', busy, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-55 whitespace-nowrap',
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
        variant === 'primary' && 'bg-ink text-text-inverse hover:bg-ink-3 active:bg-ink-2',
        variant === 'secondary' && 'border border-line-strong bg-surface text-text hover:bg-sunk active:bg-line',
        variant === 'ghost' && 'text-text hover:bg-sunk',
        variant === 'quiet' && 'text-link hover:underline px-0 h-auto',
        variant === 'danger' && 'bg-bad text-white hover:brightness-110',
        className,
      )}
      {...rest}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
})

export function Crumbs({ items }: { items: { label: string; to?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-xs text-text-muted">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1">
          {i > 0 && <ChevronRight className="h-3 w-3 text-text-faint" aria-hidden />}
          {it.to ? (
            <Link to={it.to} className="hover:text-link hover:underline">
              {it.label}
            </Link>
          ) : (
            <span aria-current="page" className="text-text">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  )
}

export function PageHeader({ title, sub, crumbs, actions }: { title: ReactNode; sub?: ReactNode; crumbs?: { label: string; to?: string }[]; actions?: ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {crumbs && <div className="mb-1.5"><Crumbs items={crumbs} /></div>}
        <h1 className="text-[22px] font-semibold leading-tight">{title}</h1>
        {sub && <div className="mt-1 text-[13px] text-text-muted">{sub}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded bg-line/70', className)} />
}

export function LoadingBlock({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2.5 py-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={clsx('h-4', i % 3 === 2 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-md border border-dashed border-line-strong bg-surface/60 px-5 py-6">
      <div className="text-[13px] font-semibold">{title}</div>
      {children && <div className="max-w-prose text-[13px] text-text-muted">{children}</div>}
      {action}
    </div>
  )
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong'
  const status = (error as any)?.status
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-bad/30 bg-bad-soft px-4 py-3 text-[13px]">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-bad" aria-hidden />
      <div className="flex-1">
        <div className="font-semibold text-bad">{status === 404 ? 'Not found' : status === 403 ? 'Not permitted' : 'Could not load this view'}</div>
        <div className="text-text">{msg}</div>
      </div>
      {retry && status !== 404 && status !== 403 && <Button size="sm" onClick={retry}>Try again</Button>}
    </div>
  )
}

export function Modal({ open, onOpenChange, title, description, children, wide }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: ReactNode; wide?: boolean
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content
          className={clsx('fixed left-1/2 top-[8vh] z-50 max-h-[84vh] w-[calc(100vw-32px)] -translate-x-1/2 overflow-y-auto rounded-md border border-line bg-surface p-5 shadow-pop', wide ? 'max-w-3xl' : 'max-w-lg')}
        >
          <Dialog.Title className="text-base font-semibold">{title}</Dialog.Title>
          {description ? <Dialog.Description className="mt-1 text-[13px] text-text-muted">{description}</Dialog.Description> : <Dialog.Description className="sr-only">{title}</Dialog.Description>}
          <div className="mt-4">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function Field({ label, error, hint, children, htmlFor }: { label: string; error?: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div>
      <label className="field-label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-text-faint">{hint}</p>}
      {error && <p className="mt-1 text-xs text-bad" role="alert">{error}</p>}
    </div>
  )
}

export function KV({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={clsx('grid grid-cols-[minmax(110px,34%)_1fr] gap-x-4 text-[13px]', className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="border-b border-line py-1.5 text-text-muted">{k}</dt>
          <dd className="min-w-0 break-words border-b border-line py-1.5">{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Pill({ children, tone = 'idle' }: { children: ReactNode; tone?: 'idle' | 'ink' | 'warn' | 'ok' | 'bad' }) {
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-px text-[11px] font-medium',
      tone === 'idle' && 'bg-sunk text-text-muted', tone === 'ink' && 'bg-ink text-text-inverse', tone === 'warn' && 'bg-warn-soft text-warn',
      tone === 'ok' && 'bg-ok-soft text-ok', tone === 'bad' && 'bg-bad-soft text-bad')}>
      {children}
    </span>
  )
}

export function SyntheticBadge() {
  return <span title="Synthetic test data — not an official record" className="inline-flex items-center rounded-sm border border-warn/40 bg-warn-soft px-1.5 py-px text-[10.5px] font-semibold text-warn">Test data</span>
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx('font-mono text-[12px]', className)}>{children}</span>
}
