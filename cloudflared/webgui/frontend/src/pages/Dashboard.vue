<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-bold text-gray-900">Dashboard</h1>

    <!-- Restarting banner -->
    <div
      v-if="tunnelStore.restarting"
      class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700"
    >
      Add-on is restarting to apply the configuration — this page reconnects
      automatically...
    </div>

    <!-- First-run guidance -->
    <div
      v-if="setupStore.state?.unconfigured"
      class="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700"
    >
      <span class="font-medium">Welcome!</span> The add-on is not configured
      yet, so the tunnel is stopped.
      <router-link to="/setup" class="font-medium underline">
        Open the Setup page
      </router-link>
      to get your tunnel running in a few minutes.
    </div>

    <!-- Setup failure guidance -->
    <div
      v-else-if="setupStore.state?.prepare_failed"
      class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      <span class="font-medium">The last tunnel setup attempt failed.</span>
      See the
      <router-link to="/logs" class="font-medium underline">Logs</router-link>
      for details, fix it on the
      <router-link to="/config" class="font-medium underline">Config</router-link>
      page, then restart. The add-on also retries automatically every 5
      minutes in case the failure was transient.
    </div>

    <!-- Status Cards -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <TunnelStatus :tunnel="tunnelStore.health?.tunnel ?? null" />

      <StatusCard
        title="Mode"
        :badge="mode"
        :variant="mode === 'token' ? 'green' : 'gray'"
      >
        <p class="text-sm text-gray-600">{{ modeDescription }}</p>
      </StatusCard>

      <StatusCard
        title="Add-on"
        :badge="tunnelStore.health?.addon_state ?? 'unknown'"
        :variant="tunnelStore.health?.supervisor_connected ? 'green' : 'red'"
      >
        <p class="text-sm text-gray-600">
          <template v-if="tunnelStore.health?.addon_version">
            Version {{ tunnelStore.health.addon_version }} —
          </template>
          {{
            tunnelStore.health?.supervisor_connected
              ? 'Supervisor connected'
              : 'Supervisor unreachable'
          }}
        </p>
      </StatusCard>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-3">
      <button
        class="rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-amber-700 disabled:opacity-50"
        :disabled="tunnelStore.restarting"
        @click="onRestart"
      >
        {{ tunnelStore.restarting ? 'Restarting...' : 'Restart Add-on' }}
      </button>
      <p class="text-xs text-gray-400">
        Restarting re-runs the tunnel setup and applies the saved
        configuration (the GUI drops out for a few seconds).
      </p>
    </div>

    <!-- Error display -->
    <div
      v-if="tunnelStore.error"
      class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      {{ tunnelStore.error }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useTunnelStore } from '@/stores/tunnel'
import { useConfigStore } from '@/stores/config'
import { useSetupStore } from '@/stores/setup'
import TunnelStatus from '@/components/TunnelStatus.vue'
import StatusCard from '@/components/StatusCard.vue'

const tunnelStore = useTunnelStore()
const configStore = useConfigStore()
const setupStore = useSetupStore()

const mode = computed(() =>
  configStore.options ? (configStore.options.tunnel_token_set ? 'token' : 'local') : 'unknown'
)

const modeDescription = computed(() => {
  if (mode.value === 'token')
    return 'Remote-managed tunnel (Cloudflare dashboard token) — all other options are ignored.'
  if (mode.value === 'local')
    return 'Local-managed tunnel (cert.pem) — configured by this add-on.'
  if (configStore.error) return `Could not load options: ${configStore.error}`
  return 'Loading...'
})

function onRestart() {
  if (window.confirm('Restart the add-on now? The tunnel and this GUI will briefly disconnect.')) {
    tunnelStore.restartAddon()
  }
}

onMounted(() => {
  tunnelStore.fetchHealth()
  configStore.fetchOptions()
  setupStore.startPolling(5000)
})
onUnmounted(() => setupStore.stopPolling())
</script>
