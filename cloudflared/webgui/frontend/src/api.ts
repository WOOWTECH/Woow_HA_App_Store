/**
 * Tiny fetch helpers that resolve every request RELATIVE to the current
 * document. Under Home Assistant Ingress the app lives at
 * /api/hassio_ingress/<token>/, so absolute paths would escape the ingress
 * prefix — relative resolution keeps everything inside it.
 */

export function apiUrl(path: string): string {
  return new URL(path, document.baseURI).toString()
}

export function wsUrl(path: string): string {
  const u = new URL(path, document.baseURI)
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
  return u.toString()
}

function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI/pydantic 422 validation errors
    return detail
      .map((d) => {
        const loc = Array.isArray(d?.loc) ? d.loc.slice(1).join('.') : ''
        return loc ? `${loc}: ${d?.msg ?? ''}` : String(d?.msg ?? '')
      })
      .filter(Boolean)
      .join('; ')
  }
  return JSON.stringify(detail)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let message = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail !== undefined) message = formatDetail(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}
