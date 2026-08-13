<template>
  <div class="flex h-full flex-col overflow-hidden rounded-xl border border-gray-200 shadow-sm">
    <!-- Status bar -->
    <div class="flex items-center gap-2 border-b border-gray-200 bg-white px-4 py-2">
      <span
        class="h-2 w-2 rounded-full"
        :class="connected ? 'bg-green-500' : 'bg-red-500'"
      />
      <span class="text-xs text-gray-500">
        {{ connected ? 'Connected' : 'Disconnected' }}
      </span>
      <div class="ml-auto flex items-center gap-3">
        <label class="flex items-center gap-1.5 text-xs text-gray-400">
          <input
            v-model="autoScroll"
            type="checkbox"
            class="rounded border-gray-300 text-cf-orange focus:ring-cf-orange"
          />
          Auto-scroll
        </label>
        <button
          class="text-xs text-gray-400 hover:text-gray-600"
          @click="$emit('clear')"
        >
          Clear
        </button>
        <button
          class="text-xs text-gray-400 hover:text-gray-600"
          @click="downloadLogs"
        >
          Download
        </button>
      </div>
    </div>

    <!-- Log output -->
    <div
      ref="logContainer"
      class="flex-1 overflow-y-auto bg-gray-900 p-4 font-mono text-xs leading-5"
    >
      <div
        v-for="(line, i) in messages"
        :key="i"
        :class="lineClass(line)"
      >
        {{ line }}
      </div>
      <div v-if="messages.length === 0" class="text-gray-600">
        Waiting for logs...
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{
  messages: string[]
  connected: boolean
}>()

defineEmits<{
  clear: []
}>()

const autoScroll = ref(true)
const logContainer = ref<HTMLElement | null>(null)

function lineClass(line: string): string {
  const lower = line.toLowerCase()
  if (lower.includes('err') || lower.includes('fatal')) return 'text-red-400'
  if (lower.includes('warn')) return 'text-yellow-400'
  if (lower.includes('debug')) return 'text-gray-500'
  return 'text-green-400'
}

function downloadLogs() {
  const text = props.messages.join('\n')
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `cloudflared-logs-${Date.now()}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

watch(
  () => props.messages.length,
  async () => {
    if (autoScroll.value && logContainer.value) {
      await nextTick()
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  }
)
</script>
