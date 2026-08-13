import { ref, onUnmounted } from 'vue'
import { wsUrl } from '@/api'

export function useWebSocket(path: string) {
  const messages = ref<string[]>([])
  const connected = ref(false)
  const error = ref<string | null>(null)
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let disposed = false
  let manualClose = false
  const MAX_LINES = 2000

  function teardownSocket() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      // Suppress the auto-reconnect that onclose would otherwise schedule.
      ws.onclose = null
      ws.onmessage = null
      ws.onerror = null
      ws.close()
      ws = null
    }
  }

  function connect() {
    if (disposed) return
    manualClose = false
    // Never allow duplicate sockets/timers from repeated connect() calls.
    teardownSocket()

    // Resolved relative to the current document so the WebSocket stays
    // inside the Home Assistant Ingress path prefix.
    ws = new WebSocket(wsUrl(path))

    ws.onopen = () => {
      connected.value = true
      error.value = null
      // The server replays its buffer on connect — start from a clean slate
      // to avoid duplicated lines after a reconnect.
      messages.value = []
    }

    ws.onmessage = (event) => {
      messages.value.push(event.data)
      if (messages.value.length > MAX_LINES) {
        messages.value = messages.value.slice(-MAX_LINES)
      }
    }

    ws.onerror = () => {
      error.value = 'WebSocket connection error'
    }

    ws.onclose = () => {
      connected.value = false
      if (!disposed && !manualClose) {
        reconnectTimer = setTimeout(connect, 3000)
      }
    }
  }

  /** Stop streaming (reconnectable — Connect works again afterwards). */
  function disconnect() {
    manualClose = true
    teardownSocket()
    connected.value = false
  }

  function clear() {
    messages.value = []
  }

  onUnmounted(() => {
    disposed = true
    teardownSocket()
  })

  return { messages, connected, error, connect, disconnect, clear }
}
