import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import type { WizardState } from '@/types'

/**
 * Setup wizard store — purely observational. The forked `prepare` script
 * does the real work (login, tunnel creation, DNS) on every add-on start;
 * the wizard polls its progress and surfaces the Cloudflare authorization
 * URL captured from the log stream.
 */
export const useSetupStore = defineStore('setup', () => {
  const state = ref<WizardState | null>(null)
  const error = ref<string | null>(null)
  let pollInterval: ReturnType<typeof setInterval> | null = null

  async function fetchState() {
    try {
      state.value = await api<WizardState>('api/wizard/state')
      error.value = null
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  function startPolling(intervalMs = 3000) {
    stopPolling()
    fetchState()
    pollInterval = setInterval(fetchState, intervalMs)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  return { state, error, fetchState, startPolling, stopPolling }
})
