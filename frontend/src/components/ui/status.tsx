import clsx from 'clsx'

/**
 * Shape-coded result marks. Each verification state has a distinct glyph AND colour,
 * so status never depends on colour alone.
 */
type Tone = 'ok' | 'warn' | 'bad' | 'sim' | 'idle'

const STATE: Record<string, { label: string; tone: Tone; glyph: string }> = {
  verified: { label: 'Verified', tone: 'ok', glyph: 'check' },
  resolved: { label: 'Resolved', tone: 'ok', glyph: 'resolved' },
  mismatch: { label: 'Mismatch detected', tone: 'bad', glyph: 'cross' },
  expired: { label: 'Expired', tone: 'bad', glyph: 'clock' },
  missing: { label: 'Missing', tone: 'bad', glyph: 'empty' },
  manual_review: { label: 'Manual review required', tone: 'warn', glyph: 'eye' },
  inconclusive: { label: 'Inconclusive', tone: 'warn', glyph: 'half' },
  escalated: { label: 'Escalated', tone: 'warn', glyph: 'up' },
  pending: { label: 'Pending', tone: 'idle', glyph: 'ring' },
  source_unavailable: { label: 'External verification unavailable', tone: 'idle', glyph: 'gap' },
  rejected: { label: 'Rejected by officer', tone: 'bad', glyph: 'cross' },
  simulated: { label: 'Simulated — not verified', tone: 'sim', glyph: 'hatch' },
  not_reevaluated: { label: 'Not re-evaluated', tone: 'idle', glyph: 'ring' },
  unchecked: { label: 'Not checked', tone: 'idle', glyph: 'ring' },
}

const TONE: Record<Tone, string> = {
  ok: 'text-ok bg-ok-soft border-ok/25',
  warn: 'text-warn bg-warn-soft border-warn/30',
  bad: 'text-bad bg-bad-soft border-bad/25',
  sim: 'text-sim bg-sim-soft border-sim/30',
  idle: 'text-idle bg-idle-soft border-idle/25',
}

export function stateInfo(s?: string) {
  return STATE[s ?? ''] ?? { label: s ?? '—', tone: 'idle' as Tone, glyph: 'ring' }
}

export function Glyph({ state, size = 12 }: { state?: string; size?: number }) {
  const g = stateInfo(state).glyph
  const s = size
  const common = { width: s, height: s, viewBox: '0 0 12 12', 'aria-hidden': true as const, className: 'shrink-0' }
  switch (g) {
    case 'check':
      return <svg {...common}><rect x=".5" y=".5" width="11" height="11" rx="2" fill="currentColor" /><path d="M3 6.2l2 2 4-4.4" stroke="#fff" strokeWidth="1.6" fill="none" /></svg>
    case 'resolved':
      return <svg {...common}><rect x="1" y="1" width="10" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M3.2 6.2l2 2 3.8-4.2" stroke="currentColor" strokeWidth="1.6" fill="none" /></svg>
    case 'cross':
      return <svg {...common}><rect x=".5" y=".5" width="11" height="11" rx="2" fill="currentColor" /><path d="M3.5 3.5l5 5M8.5 3.5l-5 5" stroke="#fff" strokeWidth="1.6" /></svg>
    case 'clock':
      return <svg {...common}><circle cx="6" cy="6" r="5.3" fill="currentColor" /><path d="M6 3v3.2l2 1.3" stroke="#fff" strokeWidth="1.4" fill="none" /></svg>
    case 'empty':
      return <svg {...common}><rect x="1" y="1" width="10" height="10" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2 1.6" /></svg>
    case 'eye':
      return <svg {...common}><path d="M6 1l5.2 9.5H.8z" fill="currentColor" /><path d="M6 4.3v3" stroke="#fff" strokeWidth="1.4" /><circle cx="6" cy="8.7" r=".8" fill="#fff" /></svg>
    case 'half':
      return <svg {...common}><circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M6 1a5 5 0 0 1 0 10z" fill="currentColor" /></svg>
    case 'up':
      return <svg {...common}><path d="M6 1l5 6H8v4H4V7H1z" fill="currentColor" /></svg>
    case 'gap':
      return <svg {...common}><circle cx="6" cy="6" r="5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeDasharray="3 2" /><path d="M3.5 6h5" stroke="currentColor" strokeWidth="1.4" /></svg>
    case 'hatch':
      return <svg {...common}><defs><pattern id="h" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.2" height="3" fill="currentColor" /></pattern></defs><rect x="1" y="1" width="10" height="10" rx="2" fill="url(#h)" stroke="currentColor" strokeWidth="1" /></svg>
    default:
      return <svg {...common}><circle cx="6" cy="6" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  }
}

export function StatusTag({ state, label, size = 'md', className }: { state?: string; label?: string; size?: 'sm' | 'md'; className?: string }) {
  const info = stateInfo(state)
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-sm border font-medium whitespace-nowrap',
        size === 'sm' ? 'px-1.5 py-px text-[11px]' : 'px-2 py-0.5 text-xs',
        TONE[info.tone],
        className,
      )}
    >
      <Glyph state={state} size={size === 'sm' ? 10 : 12} />
      {label ?? info.label}
    </span>
  )
}

export function Severity({ level }: { level?: string }) {
  const bars = level === 'high' ? 3 : level === 'medium' ? 2 : 1
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-text-muted" title={`${level} severity`}>
      <span className="inline-flex items-end gap-[2px]" aria-hidden>
        {[1, 2, 3].map((i) => (
          <span key={i} className={clsx('w-[3px] rounded-[1px]', i <= bars ? (level === 'high' ? 'bg-bad' : level === 'medium' ? 'bg-warn' : 'bg-idle') : 'bg-line')} style={{ height: 4 + i * 3 }} />
        ))}
      </span>
      <span className="capitalize">{level}</span>
    </span>
  )
}

export function Certainty({ value }: { value?: string }) {
  if (!value || value === 'n/a') return null
  const map: Record<string, string> = {
    confirmed: 'Established by rule',
    suspected: 'Indicator — not proof',
    inconclusive: 'Inconclusive',
  }
  return (
    <span className={clsx('text-xs', value === 'confirmed' ? 'text-text' : 'text-warn')}>
      {map[value] ?? value}
    </span>
  )
}

const MODE: Record<string, { label: string; cls: string }> = {
  live: { label: 'Live source', cls: 'border-ok/40 text-ok' },
  simulated: { label: 'Simulated demo data', cls: 'border-sim/50 text-sim hatch-bg' },
  not_configured: { label: 'Not configured', cls: 'border-idle/40 text-idle' },
  disabled: { label: 'Disabled', cls: 'border-idle/40 text-idle' },
}

export function ModeTag({ mode }: { mode?: string }) {
  const m = MODE[mode ?? ''] ?? { label: mode ?? '—', cls: 'border-line text-text-muted' }
  return <span className={clsx('inline-flex items-center rounded-sm border bg-surface px-1.5 py-px text-[11px] font-medium', m.cls)}>{m.label}</span>
}

export function OriginTag({ origin, reviewState }: { origin?: string; reviewState?: string }) {
  if (origin === 'manual') return <span className="text-xs text-text-muted">Recorded by officer</span>
  if (reviewState === 'confirmed') return <span className="text-xs text-text">Automated · confirmed by officer</span>
  if (reviewState === 'dismissed') return <span className="text-xs text-text-muted line-through decoration-text-faint">Automated · dismissed</span>
  return <span className="text-xs text-text-muted">Automated · not yet reviewed</span>
}
