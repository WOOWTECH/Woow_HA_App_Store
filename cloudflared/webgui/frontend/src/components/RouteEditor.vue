<template>
  <div class="flex flex-col gap-3">
    <div
      v-for="(route, i) in props.routes"
      :key="i"
      class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm"
    >
      <div class="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div class="flex-1">
          <label class="mb-1 block text-xs font-medium text-gray-500">Hostname</label>
          <input
            :value="route.hostname"
            type="text"
            placeholder="app.example.com"
            class="w-full rounded-lg border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1"
            :class="
              errors[i]
                ? 'border-red-300 focus:border-red-500 focus:ring-red-500'
                : 'border-gray-300 focus:border-cf-orange focus:ring-cf-orange'
            "
            @input="setHostname(i, ($event.target as HTMLInputElement).value)"
          />
          <p v-if="errors[i]" class="mt-1 text-xs text-red-600" data-test="hostname-error">
            {{ errors[i] }}
          </p>
        </div>

        <div class="flex-1">
          <label class="mb-1 block text-xs font-medium text-gray-500">Service</label>
          <input
            :value="route.service"
            type="text"
            placeholder="http://localhost:8080"
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-cf-orange focus:outline-none focus:ring-1 focus:ring-cf-orange"
            @input="setService(i, ($event.target as HTMLInputElement).value)"
          />
        </div>

        <div class="flex items-center gap-4 pt-1 sm:pt-7">
          <label class="flex items-center gap-1.5 whitespace-nowrap text-xs text-gray-500">
            <input
              :checked="route.disableChunkedEncoding"
              type="checkbox"
              class="rounded border-gray-300 text-cf-orange focus:ring-cf-orange"
              @change="setDisableChunked(i, ($event.target as HTMLInputElement).checked)"
            />
            Disable chunked
          </label>
          <button
            type="button"
            class="text-xs font-medium text-red-500 hover:text-red-700"
            data-test="remove-row"
            @click="removeRow(i)"
          >
            Remove
          </button>
        </div>
      </div>
    </div>

    <div v-if="props.routes.length === 0" class="text-sm text-gray-400">
      No hosts added yet.
    </div>

    <div>
      <button
        type="button"
        class="rounded-lg border border-dashed border-gray-300 px-4 py-2 text-sm font-medium text-gray-600 hover:border-cf-orange hover:text-cf-orange"
        data-test="add-row"
        @click="addRow"
      >
        + Add host
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Route } from '@/types'
import { hostnameError } from '@/utils/hostname'

const props = defineProps<{
  routes: Route[]
}>()

const emit = defineEmits<{
  'update:routes': [Route[]]
}>()

const errors = computed<(string | null)[]>(() =>
  props.routes.map((r) => hostnameError(r.hostname))
)

const hasErrors = computed<boolean>(() => errors.value.some((e) => e !== null))

function update(routes: Route[]): void {
  emit('update:routes', routes)
}

function addRow(): void {
  update([...props.routes, { hostname: '', service: '', disableChunkedEncoding: false }])
}

function removeRow(index: number): void {
  update(props.routes.filter((_, i) => i !== index))
}

function setHostname(index: number, value: string): void {
  update(props.routes.map((r, i) => (i === index ? { ...r, hostname: value } : r)))
}

function setService(index: number, value: string): void {
  update(props.routes.map((r, i) => (i === index ? { ...r, service: value } : r)))
}

function setDisableChunked(index: number, value: boolean): void {
  update(props.routes.map((r, i) => (i === index ? { ...r, disableChunkedEncoding: value } : r)))
}

defineExpose<{ hasErrors: boolean }>({
  get hasErrors() {
    return hasErrors.value
  },
})
</script>
