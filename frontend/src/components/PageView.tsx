import { useEffect, useRef } from 'react'
import clsx from 'clsx'

export type Highlight = { page: number; bbox: number[]; tone: 'field' | 'alert' } | null

export function PageView({ versionId, pages, highlight, zoom = 1 }: { versionId: number; pages: number; highlight: Highlight; zoom?: number }) {
  const refs = useRef<(HTMLDivElement | null)[]>([])
  useEffect(() => {
    if (highlight) refs.current[highlight.page - 1]?.querySelector('[data-hl]')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [highlight])
  return (
    <div className="space-y-3">
      {Array.from({ length: Math.max(pages, 1) }).map((_, i) => (
        <div key={i} ref={(el) => (refs.current[i] = el)} className="relative mx-auto bg-white shadow-lift" style={{ width: `${zoom * 100}%` }}>
          <img src={`/api/reviewer/document-versions/${versionId}/pages/${i + 1}.png`} alt={`Page ${i + 1}`} className="block w-full select-none" loading="lazy" />
          {highlight && highlight.page === i + 1 && highlight.bbox && (
            <div data-hl aria-hidden className={clsx('pointer-events-none absolute rounded-[2px] ring-2', highlight.tone === 'alert' ? 'bg-bad/15 ring-bad' : 'bg-[#f2c94c]/35 ring-[#c99a06]')}
              style={{ left: `${highlight.bbox[0] * 100 - 0.6}%`, top: `${highlight.bbox[1] * 100 - 0.4}%`, width: `${(highlight.bbox[2] - highlight.bbox[0]) * 100 + 1.2}%`, height: `${(highlight.bbox[3] - highlight.bbox[1]) * 100 + 0.8}%` }} />
          )}
          <span className="absolute bottom-1 right-2 text-[10px] text-text-faint">p.{i + 1}</span>
        </div>
      ))}
    </div>
  )
}

