/**
 * Front-end hostname pre-check, kept consistent with the backend
 * `VALID_HOSTNAME_RE` in `backend/models.py` (which mirrors the forked
 * prepare script): lowercase (incl. äöüß), no protocol, no port.
 */
export const VALID_HOSTNAME_RE =
  /^(([a-z0-9äöüß]|[a-z0-9äöüß][a-z0-9äöüß-]*[a-z0-9äöüß])\.)*([a-z0-9]|[a-z0-9][a-z0-9-]*[a-z0-9])$/

/**
 * Returns a human-readable error message for an invalid hostname,
 * or `null` when the hostname is valid.
 */
export function hostnameError(raw: string): string | null {
  const value = raw.trim()
  if (!value) return 'Hostname must not be empty'
  if (value.includes('://')) return "Do not include the protocol (e.g. 'https://')"
  if (value.includes(':')) return "Do not include a port (e.g. ':8123')"
  if (value !== value.toLowerCase()) return 'Use lowercase characters only'
  if (!VALID_HOSTNAME_RE.test(value)) {
    return "Invalid hostname (lowercase letters, digits, '-' and '.' only)"
  }
  return null
}
