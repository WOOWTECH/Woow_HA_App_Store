<template>
  <StatusCard title="Tunnel Status" :badge="badge" :variant="variant">
    <div class="space-y-1.5 text-sm text-gray-700">
      <div v-if="tunnel">
        <template v-if="tunnel.status === 'running'">
          Tunnel is connected ({{ tunnel.ready_connections }} edge
          connection{{ tunnel.ready_connections === 1 ? '' : 's' }})
        </template>
        <template v-else-if="tunnel.status === 'starting'">
          Tunnel is starting up...
        </template>
        <template v-else>
          Tunnel is not running
        </template>
      </div>
      <div v-else class="text-gray-400">Status unknown</div>
    </div>
  </StatusCard>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TunnelStatus } from '@/types'
import StatusCard from './StatusCard.vue'

const props = defineProps<{
  tunnel: TunnelStatus | null
}>()

const badge = computed(() => props.tunnel?.status ?? 'unknown')

const variant = computed(() => {
  switch (props.tunnel?.status) {
    case 'running':
      return 'green'
    case 'starting':
      return 'yellow'
    case 'stopped':
      return 'red'
    default:
      return 'gray'
  }
})
</script>
