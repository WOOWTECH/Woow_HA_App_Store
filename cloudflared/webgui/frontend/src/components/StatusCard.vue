<template>
  <div
    class="rounded-xl border p-5 shadow-sm"
    :class="borderClass"
  >
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-medium text-gray-500">{{ title }}</h3>
      <span
        v-if="badge"
        class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
        :class="badgeClass"
      >
        {{ badge }}
      </span>
    </div>
    <div class="mt-3">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  badge?: string
  variant?: 'green' | 'red' | 'yellow' | 'gray'
}>()

const v = computed(() => props.variant ?? 'gray')

const borderClass = computed(() => ({
  'border-green-200 bg-green-50': v.value === 'green',
  'border-red-200 bg-red-50': v.value === 'red',
  'border-yellow-200 bg-yellow-50': v.value === 'yellow',
  'border-gray-200 bg-white': v.value === 'gray',
}))

const badgeClass = computed(() => ({
  'bg-green-100 text-green-800': v.value === 'green',
  'bg-red-100 text-red-800': v.value === 'red',
  'bg-yellow-100 text-yellow-800': v.value === 'yellow',
  'bg-gray-100 text-gray-600': v.value === 'gray',
}))
</script>
