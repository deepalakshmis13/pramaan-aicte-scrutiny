import clsx from 'clsx'

type P = { level: string; score: number; reasons: { text: string; weight: number }[]; note?: string }

export function PriorityBadge({ p }: { p: P }) {
  const cls = p.level === 'high' ? 'bg-bad text-white' : p.level === 'medium' ? 'bg-warn-soft text-warn border border-warn/30' : 'bg-sunk text-text-muted'
  return (
    <span className={clsx('inline-flex items-center whitespace-nowrap rounded-sm px-1.5 py-px text-[11px] font-semibold capitalize', cls)}>
      {p.level} · {p.score}
    </span>
  )
}

/** The actual weighted factors behind a score. */
export function PriorityReasons({ p, compact }: { p: P; compact?: boolean }) {
  if (!p.reasons.length) return <span className="text-xs text-text-muted">No open factors</span>
  return (
    <ul className={clsx('text-xs', compact ? 'space-y-0' : 'space-y-0.5')}>
      {(compact ? p.reasons.slice(0, 2) : p.reasons).map((r, i) => (
        <li key={i} className="flex justify-between gap-3">
          <span>{r.text}</span>
          <span className="tabular-nums text-text-muted">+{r.weight}</span>
        </li>
      ))}
      {compact && p.reasons.length > 2 && <li className="text-text-faint">+{p.reasons.length - 2} more</li>}
    </ul>
  )
}

export function Sel({ id, label, value, onChange, options }: { id: string; label: string; value: string; onChange: (v: string) => void; options: [string, string][] }) {
  return (
    <div>
      <label className="field-label" htmlFor={id}>{label}</label>
      <select id={id} className="input pr-7" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  )
}
