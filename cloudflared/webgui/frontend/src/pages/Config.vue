<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-bold text-gray-900">Configuration</h1>
    <p class="text-sm text-gray-500">
      These are the add-on's Supervisor options — the same ones shown on the
      Home Assistant add-on configuration page. Saving here writes them back
      through the Supervisor, so both views always stay in sync.
    </p>

    <div v-if="configStore.loading && !configStore.options" class="text-gray-500">
      Loading...
    </div>

    <form v-else class="space-y-6" @submit.prevent="onSave(false)">
      <!-- Remote-managed (token) -->
      <fieldset class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <legend class="px-2 text-sm font-semibold text-gray-700">
          Remote-Managed Tunnel (tunnel_token)
        </legend>
        <div class="mt-2 space-y-3">
          <p class="text-xs text-gray-400">
            Paste a tunnel token from the Cloudflare Zero Trust dashboard to
            use a remote-managed tunnel.
            <span class="font-medium">When a token is set, all other options
            below are ignored</span> (identical to the original add-on).
          </p>
          <TokenInput
            :masked-value="configStore.options?.tunnel_token_masked ?? ''"
            placeholder="eyJhIjoiLi4uIiwidCI6Ii4uLiIsInMiOiIuLi4ifQ=="
            @update:token="tokenInput = $event"
          />
          <div class="flex items-center gap-3">
            <span
              class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
              :class="
                configStore.options?.tunnel_token_set
                  ? 'bg-green-100 text-green-800'
                  : 'bg-gray-100 text-gray-600'
              "
            >
              {{ configStore.options?.tunnel_token_set ? 'token configured' : 'no token' }}
            </span>
            <button
              v-if="configStore.options?.tunnel_token_set"
              type="button"
              class="text-xs font-medium text-red-500 hover:text-red-700"
              @click="clearToken = !clearToken"
            >
              {{ clearToken ? 'Keep token on save' : 'Remove token on save (switch to local mode)' }}
            </button>
          </div>
          <p v-if="clearToken" class="text-xs text-amber-600">
            The stored token will be removed when you save.
          </p>
        </div>
      </fieldset>

      <!-- Home Assistant hostname -->
      <fieldset class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <legend class="px-2 text-sm font-semibold text-gray-700">Home Assistant</legend>
        <div class="mt-2 space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">External Hostname</label>
            <p class="mb-1 text-xs text-gray-400">
              Domain/subdomain for remote access to Home Assistant
              (e.g. ha.example.com). Home Assistant's port and SSL settings
              are detected automatically.
            </p>
            <input
              v-model="form.external_hostname"
              type="text"
              placeholder="ha.example.com"
              class="mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-1"
              :class="
                externalHostnameError
                  ? 'border-red-300 focus:border-red-500 focus:ring-red-500'
                  : 'border-gray-300 focus:border-cf-orange focus:ring-cf-orange'
              "
            />
            <p v-if="externalHostnameError" class="mt-1 text-xs text-red-600">
              {{ externalHostnameError }}
            </p>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700">Tunnel Name</label>
            <p class="mb-1 text-xs text-gray-400">
              Name of the Cloudflare Tunnel (local-managed mode). Default: homeassistant
            </p>
            <input
              v-model="form.tunnel_name"
              type="text"
              placeholder="homeassistant"
              class="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-cf-orange focus:outline-none focus:ring-1 focus:ring-cf-orange"
            />
          </div>
        </div>
      </fieldset>

      <!-- Additional Hosts -->
      <fieldset class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <legend class="px-2 text-sm font-semibold text-gray-700">Additional Hosts</legend>
        <p class="mt-1 mb-3 text-xs text-gray-400">
          Route additional hostnames through the tunnel to other local
          services. DNS entries are created automatically on start.
        </p>
        <RouteEditor :routes="form.routes" @update:routes="form.routes = $event" />
      </fieldset>

      <!-- Catch-All -->
      <fieldset class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <legend class="px-2 text-sm font-semibold text-gray-700">Catch-All</legend>
        <div class="mt-2 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <span class="text-sm font-medium text-gray-700">Nginx Proxy Manager</span>
              <p class="text-xs text-gray-400">
                Route unmatched traffic to the Nginx Proxy Manager add-on
                (mutually exclusive with a custom catch-all URL).
              </p>
            </div>
            <button
              type="button"
              class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200"
              :class="form.nginx_proxy_manager ? 'bg-cf-orange' : 'bg-gray-200'"
              @click="toggleNpm"
            >
              <span
                class="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform duration-200"
                :class="form.nginx_proxy_manager ? 'translate-x-5' : 'translate-x-0'"
              />
            </button>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700">Catch-All Service URL</label>
            <p class="mb-1 text-xs text-gray-400">
              Fallback service for hostnames not defined above (e.g. a reverse proxy).
            </p>
            <input
              v-model="form.catch_all_service"
              :disabled="form.nginx_proxy_manager"
              type="text"
              placeholder="http://192.168.1.100"
              class="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-cf-orange focus:outline-none focus:ring-1 focus:ring-cf-orange disabled:bg-gray-100 disabled:text-gray-400"
            />
          </div>
        </div>
      </fieldset>

      <!-- Advanced -->
      <fieldset class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <legend class="px-2 text-sm font-semibold text-gray-700">Advanced</legend>
        <div class="mt-2 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <span class="text-sm font-medium text-gray-700">Post-Quantum Cryptography</span>
              <p class="text-xs text-gray-400">
                Restricts the tunnel to QUIC transport — may cause issues for some users.
              </p>
            </div>
            <button
              type="button"
              class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200"
              :class="form.post_quantum ? 'bg-cf-orange' : 'bg-gray-200'"
              @click="form.post_quantum = !form.post_quantum"
            >
              <span
                class="pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform duration-200"
                :class="form.post_quantum ? 'translate-x-5' : 'translate-x-0'"
              />
            </button>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700">Add-on Log Level</label>
            <p class="mb-1 text-xs text-gray-400">
              Verbosity of the add-on's own log output (bashio). For the
              tunnel's log level use a run parameter: --loglevel=debug
            </p>
            <select
              v-model="form.log_level"
              class="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-cf-orange focus:outline-none focus:ring-1 focus:ring-cf-orange"
            >
              <option value="">(default: info)</option>
              <option v-for="lvl in LOG_LEVELS" :key="lvl" :value="lvl">{{ lvl }}</option>
            </select>
          </div>

          <div>
            <label class="block text-sm font-medium text-gray-700">Run Parameters</label>
            <p class="mb-1 text-xs text-gray-400">
              One per line, format --flag=value. Allowed flags:
              --edge-bind-address, --edge-ip-version, --grace-period,
              --ha-connections, --logfile, --loglevel, --pidfile, --protocol,
              --region, --retries, --tag
            </p>
            <textarea
              v-model="runParametersText"
              rows="3"
              placeholder="--loglevel=debug&#10;--region=us"
              class="mt-1 block w-full rounded-lg border px-3 py-2 font-mono text-sm shadow-sm focus:outline-none focus:ring-1"
              :class="
                runParametersError
                  ? 'border-red-300 focus:border-red-500 focus:ring-red-500'
                  : 'border-gray-300 focus:border-cf-orange focus:ring-cf-orange'
              "
            />
            <p v-if="runParametersError" class="mt-1 text-xs text-red-600">
              {{ runParametersError }}
            </p>
          </div>
        </div>
      </fieldset>

      <!-- Actions -->
      <div class="flex items-center gap-3">
        <button
          type="submit"
          class="rounded-lg border border-cf-orange bg-white px-5 py-2 text-sm font-medium text-cf-orange shadow-sm hover:bg-orange-50 disabled:opacity-50"
          :disabled="configStore.loading || hasErrors"
        >
          {{ configStore.loading ? 'Saving...' : 'Save' }}
        </button>
        <button
          type="button"
          class="rounded-lg bg-cf-orange px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-orange-600 disabled:opacity-50"
          :disabled="configStore.loading || hasErrors || tunnelStore.restarting"
          @click="onSave(true)"
        >
          Save &amp; Restart
        </button>
        <button
          type="button"
          class="rounded-lg border border-gray-300 bg-white px-5 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          @click="resetForm"
        >
          Reset
        </button>
      </div>

      <p class="text-xs text-gray-400">
        "Save" only stores the options — like the HA configuration page, a
        restart is needed before they take effect. "Save &amp; Restart" does
        both (the GUI drops out for a few seconds).
      </p>

      <!-- Feedback -->
      <div
        v-if="configStore.saved"
        class="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
      >
        Configuration saved{{ tunnelStore.restarting ? ' — restarting add-on...' : '.' }}
      </div>
      <div
        v-if="configStore.error"
        class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {{ configStore.error }}
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useTunnelStore } from '@/stores/tunnel'
import TokenInput from '@/components/TokenInput.vue'
import RouteEditor from '@/components/RouteEditor.vue'
import { hostnameError } from '@/utils/hostname'
import type { LogLevel, OptionsWrite, Route } from '@/types'

const LOG_LEVELS: LogLevel[] = [
  'trace',
  'debug',
  'info',
  'notice',
  'warning',
  'error',
  'fatal',
]

const RUN_PARAMETER_RE =
  /^(--edge-bind-address|--edge-ip-version|--grace-period|--ha-connections|--logfile|--loglevel|--pidfile|--protocol|--region|--retries|--tag)=.*$/

const configStore = useConfigStore()
const tunnelStore = useTunnelStore()

const tokenInput = ref<string | null>(null)
const clearToken = ref(false)
const runParametersText = ref('')

const form = reactive({
  external_hostname: '',
  routes: [] as Route[],
  tunnel_name: '',
  catch_all_service: '',
  nginx_proxy_manager: false,
  post_quantum: false,
  log_level: '' as '' | LogLevel,
})

const externalHostnameError = computed(() => {
  const v = form.external_hostname.trim()
  if (!v) return null
  return hostnameError(v)
})

const runParametersError = computed(() => {
  for (const line of runParametersText.value.split('\n')) {
    const param = line.trim()
    if (param && !RUN_PARAMETER_RE.test(param)) {
      return `'${param}' is not an allowed run parameter (format: --flag=value)`
    }
  }
  return null
})

const routesError = computed(() =>
  form.routes.some((r) => hostnameError(r.hostname) !== null || !r.service.trim())
)

const hasErrors = computed(
  () =>
    externalHostnameError.value !== null ||
    runParametersError.value !== null ||
    routesError.value
)

function toggleNpm() {
  form.nginx_proxy_manager = !form.nginx_proxy_manager
  if (form.nginx_proxy_manager) form.catch_all_service = ''
}

function resetForm() {
  const o = configStore.options
  tokenInput.value = null
  clearToken.value = false
  if (!o) return
  form.external_hostname = o.external_hostname
  form.routes = (o.additional_hosts || []).map((h) => ({
    hostname: h.hostname,
    service: h.service,
    disableChunkedEncoding: !!h.disableChunkedEncoding,
  }))
  form.tunnel_name = o.tunnel_name ?? ''
  form.catch_all_service = o.catch_all_service ?? ''
  form.nginx_proxy_manager = !!o.nginx_proxy_manager
  form.post_quantum = !!o.post_quantum
  form.log_level = o.log_level ?? ''
  runParametersText.value = (o.run_parameters ?? []).join('\n')
}

function payload(): OptionsWrite {
  const runParameters = runParametersText.value
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

  const body: OptionsWrite = {
    external_hostname: form.external_hostname.trim(),
    additional_hosts: form.routes.map((r) => ({
      hostname: r.hostname.trim(),
      service: r.service.trim(),
      // Only persist the flag when set, matching hand-written add-on configs.
      ...(r.disableChunkedEncoding ? { disableChunkedEncoding: true } : {}),
    })),
    tunnel_name: form.tunnel_name.trim() || null,
    catch_all_service: form.catch_all_service.trim() || null,
    nginx_proxy_manager: form.nginx_proxy_manager ? true : null,
    post_quantum: form.post_quantum ? true : null,
    run_parameters: runParameters.length ? runParameters : null,
    log_level: form.log_level || null,
  }

  if (clearToken.value) {
    body.tunnel_token = ''
  } else if (tokenInput.value) {
    body.tunnel_token = tokenInput.value
  }
  // Otherwise omit tunnel_token → backend keeps the stored token.

  return body
}

async function onSave(restart: boolean) {
  const ok = await configStore.saveOptions(payload(), restart)
  if (ok && restart) tunnelStore.markRestarting()
  if (ok) {
    clearToken.value = false
    tokenInput.value = null
  } else if (restart && configStore.error && /fetch|network|load failed/i.test(configStore.error)) {
    // The save may have succeeded with the response lost to the add-on
    // teardown — treat a network-level failure on Save & Restart as a
    // restart in flight; the health poll will confirm either way.
    tunnelStore.markRestarting()
  }
}

watch(() => configStore.options, resetForm, { immediate: true })

onMounted(() => {
  configStore.fetchOptions()
})
</script>
