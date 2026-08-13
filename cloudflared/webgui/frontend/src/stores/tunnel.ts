import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api'
import type { HealthStatus } from '@/types'

/**
 * Health / tunnel status store.
 *
 * Also tracks the "restarting" window: after a restart is requested the
 * add-on (including this GUI backend) goes down briefly. We keep polling;
 * once the backend answers again after having been unreachable, the restart
 * is considered complete.
 */
export const useTunnelStore = defineStore('tunnel', () => {
  const health = ref<HealthStatus | null>(null)
  const restarting = ref(false)
  const error = ref<string | null>(null)
  let pollInterval: ReturnType<typeof setInterval> | null = null
  let restartWatchdog: ReturnType<typeof setTimeout> | null = null
  let sawDown = false
  let restartStartedAt = 0

  const RESTART_TIMEOUT_MS = 120_000
  // If health keeps answering and we never observed the down window (a very
  // fast restart can slip between polls), assume the restart completed.
  const RESTART_ASSUME_DONE_MS = 30_000
  const POLL_NORMAL_MS = 4000
  const POLL_RESTARTING_MS = 1500

  const tunnelStatus = computed(() => health.value?.tunnel.status ?? 'unknown')

  function clearWatchdog() {
    if (restartWatchdog) {
      clearTimeout(restartWatchdog)
      restartWatchdog = null
    }
  }

  function finishRestart() {
    restarting.value = false
    sawDown = false
    clearWatchdog()
    startPolling(POLL_NORMAL_MS)
  }

  async function fetchHealth() {
    try {
      health.value = await api<HealthStatus>('api/health')
      error.value = null
      if (restarting.value) {
        if (health.value.restart_error) {
          // Supervisor rejected the restart: options were saved but NOT
          // applied — surface it instead of pretending success.
          finishRestart()
          error.value = `Restart failed — the saved options are not applied yet: ${health.value.restart_error}`
        } else if (sawDown) {
          finishRestart()
        } else if (Date.now() - restartStartedAt > RESTART_ASSUME_DONE_MS) {
          finishRestart()
        }
      }
    } catch (e: unknown) {
      if (restarting.value) {
        sawDown = true
      } else {
        error.value = e instanceof Error ? e.message : String(e)
      }
      health.value = null
    }
  }

  /** Mark a restart in flight (with a watchdog so the UI can't get stuck). */
  function markRestarting() {
    restarting.value = true
    sawDown = false
    restartStartedAt = Date.now()
    startPolling(POLL_RESTARTING_MS)
    clearWatchdog()
    restartWatchdog = setTimeout(() => {
      if (restarting.value) {
        restarting.value = false
        error.value =
          'Add-on restart timed out — check the add-on state in Home Assistant (Settings → Add-ons).'
        startPolling(POLL_NORMAL_MS)
      }
    }, RESTART_TIMEOUT_MS)
  }

  async function restartAddon() {
    error.value = null
    try {
      await api<{ result: string }>('api/restart', { method: 'POST' })
    } catch {
      // The backend may die mid-request while restarting — that's expected.
    }
    markRestarting()
  }

  function startPolling(intervalMs = POLL_NORMAL_MS) {
    stopPolling()
    fetchHealth()
    pollInterval = setInterval(fetchHealth, intervalMs)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  return {
    health,
    restarting,
    error,
    tunnelStatus,
    fetchHealth,
    restartAddon,
    markRestarting,
    startPolling,
    stopPolling,
  }
})
