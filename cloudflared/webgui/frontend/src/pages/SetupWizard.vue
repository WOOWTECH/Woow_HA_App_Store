<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-bold text-gray-900">Setup</h1>
    <p class="text-sm text-gray-500">
      The add-on performs the tunnel setup automatically on every start:
      Cloudflare authorization → tunnel creation → DNS routes → connect.
      This page tracks the progress and gives you the authorization link
      when it is needed — no digging through logs.
    </p>

    <!-- Prepare failure banner -->
    <div
      v-if="setupStore.state?.prepare_failed"
      class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      <span class="font-medium">The last tunnel setup attempt failed.</span>
      Check the Logs page for the exact error, fix the configuration on the
      Config page, then restart the add-on. The tunnel stays stopped until
      then — this GUI keeps running so you can repair it from here.
    </div>

    <!-- Token mode notice -->
    <div
      v-if="setupStore.state?.mode === 'token'"
      class="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700"
    >
      This add-on runs a <span class="font-medium">remote-managed tunnel</span>
      (tunnel_token is set). Everything is managed in the Cloudflare Zero
      Trust dashboard; the local setup steps below do not apply. Remove the
      token on the Config page to switch to local-managed mode.
    </div>

    <template v-else>
      <!-- Step 1: Configuration -->
      <WizardStep
        :index="1"
        title="Configure your hostnames"
        :done="hasMinimalConfig"
      >
        <p v-if="hasMinimalConfig" class="text-sm text-gray-600">
          Configuration present — external hostname and/or additional hosts
          are set.
        </p>
        <template v-else>
          <p class="text-sm text-gray-600">
            Set at least an external hostname (or additional hosts /
            catch-all) on the Config page, then Save &amp; Restart.
          </p>
          <router-link
            to="/config"
            class="mt-2 inline-block rounded-lg bg-cf-orange px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-orange-600"
          >
            Open Config
          </router-link>
        </template>
      </WizardStep>

      <!-- Step 2: Cloudflare authorization -->
      <WizardStep
        :index="2"
        title="Authorize with Cloudflare"
        :done="setupStore.state?.has_cert ?? false"
      >
        <p v-if="setupStore.state?.has_cert" class="text-sm text-gray-600">
          Certificate found (cert.pem) — this add-on is authorized for your
          Cloudflare zone.
        </p>
        <template v-else>
          <div v-if="setupStore.state?.login_url" class="space-y-3">
            <p class="text-sm text-gray-600">
              Open this link, sign in to Cloudflare, and authorize the domain
              you want to use:
            </p>
            <div class="flex flex-wrap items-center gap-2">
              <a
                :href="setupStore.state.login_url"
                target="_blank"
                rel="noopener"
                class="rounded-lg bg-cf-orange px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-orange-600"
              >
                Open Cloudflare authorization page
              </a>
              <button
                type="button"
                class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
                @click="copyLoginUrl"
              >
                {{ copied ? 'Copied!' : 'Copy link' }}
              </button>
            </div>
            <p class="break-all font-mono text-xs text-gray-400">
              {{ setupStore.state.login_url }}
            </p>
            <p class="text-sm text-gray-600">
              After authorizing, the add-on continues automatically — this
              page updates on its own.
            </p>
          </div>
          <p v-else class="text-sm text-gray-600">
            Waiting for the add-on to request authorization... If the add-on
            is running with a complete configuration, the link appears here
            within a few seconds of (re)starting.
          </p>
        </template>
      </WizardStep>

      <!-- Step 3: Tunnel created -->
      <WizardStep
        :index="3"
        title="Tunnel created"
        :done="setupStore.state?.has_tunnel ?? false"
      >
        <p v-if="setupStore.state?.has_tunnel" class="text-sm text-gray-600">
          Tunnel exists
          <span v-if="setupStore.state?.tunnel_uuid" class="font-mono text-xs">
            ({{ setupStore.state.tunnel_uuid }})
          </span>
        </p>
        <p v-else class="text-sm text-gray-600">
          The tunnel is created automatically right after authorization.
        </p>
      </WizardStep>

      <!-- Step 4: Connected -->
      <WizardStep
        :index="4"
        title="Tunnel connected"
        :done="setupStore.state?.tunnel_status === 'running'"
      >
        <p class="text-sm text-gray-600">
          <template v-if="setupStore.state?.tunnel_status === 'running'">
            The tunnel is up — your hostnames are reachable through
            Cloudflare.
          </template>
          <template v-else-if="setupStore.state?.tunnel_status === 'starting'">
            cloudflared is connecting to the Cloudflare edge...
          </template>
          <template v-else>
            cloudflared has not started yet. It starts automatically once the
            steps above are complete.
          </template>
        </p>
      </WizardStep>
    </template>

    <!-- Suppressed while the add-on restarts: transient fetch failures are
         expected then and would contradict our own instructions. -->
    <div
      v-if="setupStore.error && !tunnelStore.restarting"
      class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
    >
      {{ setupStore.error }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, h, defineComponent } from 'vue'
import { useSetupStore } from '@/stores/setup'
import { useConfigStore } from '@/stores/config'
import { useTunnelStore } from '@/stores/tunnel'

/** Inline step card: numbered circle + title + status. */
const WizardStep = defineComponent({
  props: {
    index: { type: Number, required: true },
    title: { type: String, required: true },
    done: { type: Boolean, default: false },
  },
  setup(props, { slots }) {
    return () =>
      h(
        'div',
        {
          class: [
            'rounded-xl border p-5 shadow-sm',
            props.done ? 'border-green-200 bg-green-50' : 'border-gray-200 bg-white',
          ],
        },
        [
          h('div', { class: 'flex items-center gap-3' }, [
            h(
              'span',
              {
                class: [
                  'flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold',
                  props.done ? 'bg-green-500 text-white' : 'bg-gray-200 text-gray-600',
                ],
              },
              props.done ? '✓' : String(props.index)
            ),
            h('h3', { class: 'text-sm font-semibold text-gray-800' }, props.title),
          ]),
          h('div', { class: 'mt-3 pl-10' }, slots.default ? slots.default() : []),
        ]
      )
  },
})

const setupStore = useSetupStore()
const tunnelStore = useTunnelStore()
const configStore = useConfigStore()
const copied = ref(false)

const hasMinimalConfig = computed(() => {
  const o = configStore.options
  if (!o) return false
  return !!(
    o.external_hostname ||
    (o.additional_hosts && o.additional_hosts.length > 0) ||
    o.catch_all_service ||
    o.nginx_proxy_manager
  )
})

async function copyLoginUrl() {
  const url = setupStore.state?.login_url
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
  } catch {
    // Clipboard API can be unavailable in iframes — fall back to a prompt.
    window.prompt('Copy the authorization URL:', url)
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 2000)
}

onMounted(() => {
  configStore.fetchOptions()
  setupStore.startPolling(3000)
})
onUnmounted(() => setupStore.stopPolling())
</script>
