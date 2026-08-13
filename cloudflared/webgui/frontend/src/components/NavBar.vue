<template>
  <nav class="border-b border-gray-200 bg-white">
    <div class="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
      <!-- Logo -->
      <div class="flex items-center gap-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-cf-orange">
          <svg class="h-5 w-5 text-white" fill="currentColor" viewBox="0 0 24 24">
            <path d="M16.5088 16.8447C16.6276 16.4437 16.5903 16.0764 16.4003 15.7916C16.2291 15.5342 15.9506 15.3876 15.6234 15.3689L8.50562 15.3045C8.44308 15.2983 8.39308 15.272 8.36808 15.2332C8.33683 15.1944 8.32433 15.1432 8.34308 15.0982L8.55558 14.4653C8.63058 14.2266 8.84933 14.0612 9.09933 14.0487L15.8209 13.9843C16.8647 13.953 18.0272 13.1452 18.4169 12.1764L18.9609 10.8277C19.0672 10.558 19.0984 10.2883 19.0547 10.0372C18.4272 7.05973 15.7672 4.83398 12.5997 4.83398C9.89308 4.83398 7.56558 6.48523 6.59933 8.82773C6.00558 8.44648 5.27433 8.27148 4.50558 8.35273C3.17433 8.49648 2.09308 9.57148 1.94308 10.8964C1.90558 11.2327 1.91808 11.5627 1.97433 11.8762C0.849326 12.1397 0.00557613 13.1389 0.00557613 14.3389C0.00557613 14.4216 0.0118261 14.5041 0.0180761 14.5866C0.0430761 14.8126 0.236826 14.9814 0.462076 14.9814L8.14308 14.9814L7.68058 16.4624C7.56183 16.8634 7.59933 17.2307 7.78933 17.5155C7.96058 17.7729 8.23933 17.9195 8.56683 17.9382L8.74433 17.9445C8.74433 17.9445 15.5522 17.882 15.6397 17.882C15.8772 17.8757 16.0959 17.7229 16.1772 17.4907L16.5088 16.8447Z" />
          </svg>
        </div>
        <span class="text-lg font-semibold text-gray-900">Cloudflared</span>
      </div>

      <!-- Navigation Links -->
      <div class="flex items-center gap-1">
        <router-link
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="rounded-lg px-3 py-2 text-sm font-medium transition-colors"
          :class="
            $route.path === link.to
              ? 'bg-cf-orange/10 text-cf-orange'
              : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
          "
        >
          {{ link.label }}
        </router-link>
      </div>

      <!-- Status Dot -->
      <div class="flex items-center gap-2">
        <span class="h-2.5 w-2.5 rounded-full" :class="statusDotClass" />
        <span class="text-xs text-gray-500">{{ statusLabel }}</span>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useTunnelStore } from '@/stores/tunnel'

const tunnelStore = useTunnelStore()

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/setup', label: 'Setup' },
  { to: '/config', label: 'Config' },
  { to: '/logs', label: 'Logs' },
]

const statusDotClass = computed(() => {
  if (tunnelStore.restarting) return 'bg-amber-500 animate-pulse'
  switch (tunnelStore.tunnelStatus) {
    case 'running':
      return 'bg-green-500'
    case 'starting':
      return 'bg-amber-500'
    case 'stopped':
      return 'bg-red-500'
    default:
      return 'bg-gray-400'
  }
})

const statusLabel = computed(() => {
  if (tunnelStore.restarting) return 'restarting add-on...'
  return tunnelStore.tunnelStatus
})

onMounted(() => tunnelStore.startPolling(4000))
onUnmounted(() => tunnelStore.stopPolling())
</script>
