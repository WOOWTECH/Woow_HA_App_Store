<template>
  <div class="relative">
    <input
      :type="visible ? 'text' : 'password'"
      :value="displayValue"
      :placeholder="placeholder"
      class="block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm shadow-sm focus:border-cf-orange focus:outline-none focus:ring-1 focus:ring-cf-orange"
      @input="onInput"
      @focus="onFocus"
    />
    <button
      type="button"
      class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600"
      @click="visible = !visible"
    >
      <svg v-if="!visible" class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      </svg>
      <svg v-else class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  maskedValue: string
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:token': [value: string | null]
}>()

const visible = ref(false)
const userTyped = ref(false)
const rawInput = ref('')

const displayValue = ref(props.maskedValue)

// Re-sync with the stored state whenever it changes (after save/reset the
// parent refetches options and the masked value must win again).
watch(
  () => props.maskedValue,
  (masked) => {
    userTyped.value = false
    rawInput.value = ''
    displayValue.value = masked
  }
)

function onFocus() {
  if (!userTyped.value && props.maskedValue) {
    displayValue.value = ''
  }
}

function onInput(e: Event) {
  const target = e.target as HTMLInputElement
  userTyped.value = true
  rawInput.value = target.value
  displayValue.value = target.value
  emit('update:token', target.value || null)
}
</script>
