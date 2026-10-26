import { useEffect, useState, useSyncExternalStore } from 'react'
import { Download, X } from 'lucide-react'
import * as Dialog from '@radix-ui/react-dialog'
import { api, errorMessage } from './api'

// Tiny external store so any component can open the PDF viewer.
let state: { path: string; title: string } | null = null
const subs = new Set<() => void>()
const emit = () => subs.forEach((s) => s())
export function openPdf(path: string, title: string) {
  state = { path, title }
  emit()
}
function close() {
  state = null
  emit()
}

export function PdfViewerHost() {
  const cur = useSyncExternalStore((cb) => (subs.add(cb), () => subs.delete(cb)), () => state)
  const [url, setUrl] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let u: string | null = null
    setUrl(null)
    setErr(null)
    if (cur) {
      api<Blob>(cur.path)
        .then((b) => { u = URL.createObjectURL(b); setUrl(u) })
        .catch((e) => setErr(errorMessage(e)))
    }
    return () => { if (u) URL.revokeObjectURL(u) }
  }, [cur])
  return (
    <Dialog.Root open={!!cur} onOpenChange={(o) => !o && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/50" />
        <Dialog.Content className="fixed inset-3 z-50 flex flex-col overflow-hidden rounded-md border border-line bg-surface shadow-pop sm:inset-8">
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
            <Dialog.Title className="truncate text-[13px] font-semibold">{cur?.title}</Dialog.Title>
            <Dialog.Description className="sr-only">PDF document viewer</Dialog.Description>
            <div className="flex items-center gap-2">
              {url && <a href={url} download={`${cur?.title ?? 'report'}.pdf`} className="inline-flex h-7 items-center gap-1.5 rounded border border-line-strong px-2.5 text-xs font-medium hover:bg-sunk"><Download className="h-3.5 w-3.5" />Download</a>}
              <Dialog.Close className="rounded p-1.5 hover:bg-sunk" aria-label="Close"><X className="h-4 w-4" /></Dialog.Close>
            </div>
          </div>
          <div className="flex-1 bg-[#d9dcd6]">
            {err ? <p role="alert" className="p-6 text-[13px] text-bad">{err}</p> : url ? <iframe title={cur?.title} src={url} className="h-full w-full" /> : <p className="p-6 text-[13px] text-text-muted">Loading PDF…</p>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
