<template>
  <div class="flex h-[calc(100vh-180px)] flex-col gap-4">
    <div class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-gray-900">Logs</h1>
      <div class="flex gap-2">
        <button
          v-if="!connected"
          class="rounded-lg bg-cf-orange px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-orange-600"
          @click="connect()"
        >
          Connect
        </button>
        <button
          v-else
          class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          @click="disconnect()"
        >
          Disconnect
        </button>
      </div>
    </div>

    <p class="text-xs text-gray-400">
      Same content as the Home Assistant add-on Log tab (bashio + cloudflared).
    </p>

    <!-- Filter -->
    <div>
      <input
        v-model="filter"
        type="text"
        placeholder="Filter logs..."
        class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-cf-orange focus:outline-none focus:ring-1 focus:ring-cf-orange"
      />
    </div>

    <!-- Log Viewer -->
    <LogViewer
      :messages="filteredMessages"
      :connected="connected"
      class="min-h-0 flex-1"
      @clear="clear()"
    />

    <!-- Error -->
    <div
      v-if="error"
      class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      {{ error }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useWebSocket } from '@/composables/useWebSocket'
import LogViewer from '@/components/LogViewer.vue'

const { messages, connected, error, connect, disconnect, clear } =
  useWebSocket('api/logs/stream')

const filter = ref('')

const filteredMessages = computed(() => {
  if (!filter.value) return messages.value
  const lower = filter.value.toLowerCase()
  return messages.value.filter((m) => m.toLowerCase().includes(lower))
})

onMounted(() => {
  connect()
})
</script>
