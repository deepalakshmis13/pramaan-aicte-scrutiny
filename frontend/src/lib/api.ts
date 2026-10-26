// Central API client. Cookies carry the session; the custom header is required by the
// backend for state-changing requests (CSRF mitigation).

export class ApiError extends Error {
  status: number
  fields?: { field: string; message: string }[]
  constructor(status: number, message: string, fields?: { field: string; message: string }[]) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

type Opts = { method?: string; body?: unknown; form?: FormData; params?: Record<string, string | number | boolean | undefined | null> }

export function qs(params?: Opts['params']) {
  if (!params) return ''
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '' && v !== false) p.set(k, String(v))
  })
  const s = p.toString()
  return s ? `?${s}` : ''
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { 'X-Requested-With': 'pramaan' }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  let res: Response
  try {
    res = await fetch(`/api${path}${qs(opts.params)}`, { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'The server could not be reached. Check that the backend is running.')
  }
  if (res.status === 401 && !path.startsWith('/auth/')) onUnauthorized?.()
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    let fields
    try {
      const j = await res.json()
      msg = j?.error?.message ?? msg
      fields = j?.error?.fields
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg), fields)
  }
  const ct = res.headers.get('content-type') || ''
  return (ct.includes('application/json') ? res.json() : (res.blob() as any)) as T
}

export const post = <T = any>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body: body ?? {} })
export const patch = <T = any>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body })
export const del = <T = any>(path: string) => api<T>(path, { method: 'DELETE' })

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.fields?.length) return `${e.message}: ${e.fields.map((f) => `${f.field} — ${f.message}`).join('; ')}`
    return e.message
  }
  return e instanceof Error ? e.message : 'Something went wrong'
}

/** Download/open a binary endpoint (PDF, CSV) using the session cookie. */
export async function openFile(path: string, filename?: string, inline = false) {
  const blob = await api<Blob>(path)
  const url = URL.createObjectURL(blob)
  if (inline) {
    window.open(url, '_blank', 'noopener')
  } else {
    const a = document.createElement('a')
    a.href = url
    a.download = filename ?? 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
