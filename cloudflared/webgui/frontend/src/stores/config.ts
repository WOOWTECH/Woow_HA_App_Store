import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import type { OptionsRead, OptionsWrite } from '@/types'

/**
 * Supervisor options store. The Supervisor is the single source of truth:
 * GET reads the stored add-on options, PUT writes them back (validated by
 * the Supervisor against the add-on schema) and optionally restarts the
 * add-on so they take effect.
 */
export const useConfigStore = defineStore('config', () => {
  const options = ref<OptionsRead | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const saved = ref(false)

  async function fetchOptions() {
    loading.value = true
    error.value = null
    try {
      options.value = await api<OptionsRead>('api/options')
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function saveOptions(
    data: OptionsWrite,
    restart = false
  ): Promise<boolean> {
    loading.value = true
    error.value = null
    saved.value = false
    try {
      await api<{ result: string; restarting: boolean }>(
        `api/options?restart=${restart}`,
        { method: 'PUT', body: JSON.stringify(data) }
      )
      saved.value = true
      if (!restart) await fetchOptions()
      return true
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
      return false
    } finally {
      loading.value = false
    }
  }

  return { options, loading, error, saved, fetchOptions, saveOptions }
})
