<template>
  <div class="space-y-6 pb-12">
    <section class="overflow-hidden rounded-3xl bg-slate-950 px-6 py-8 text-white shadow-xl sm:px-9">
      <p class="text-xs font-semibold uppercase tracking-[0.25em] text-orange-300">WOOW PaaS · 安全存取</p>
      <h1 class="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">從訂閱到安全連線，照著做就好</h1>
      <p class="mt-3 max-w-2xl text-sm leading-7 text-slate-300">先在 PaaS 選方案與設定誰能登入，再回來選擇服務。此頁會檢查每一個網址的保護，通過後才連結這台 Home Assistant。</p>
      <div class="mt-6 flex flex-wrap gap-2 text-xs font-medium">
        <span v-for="(step, index) in steps" :key="step" class="rounded-full border border-white/20 bg-white/10 px-3 py-1.5">{{ index + 1 }}　{{ step }}</span>
      </div>
    </section>

    <div v-if="error" role="alert" class="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">{{ error }}</div>
    <div v-if="message" role="status" class="rounded-xl border border-blue-200 bg-blue-50 px-5 py-4 text-sm text-blue-800">{{ message }}</div>

    <section class="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-7">
      <div class="flex items-start gap-4">
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-100 font-bold text-cf-orange">1</span>
        <div class="min-w-0 flex-1">
          <h2 class="text-lg font-semibold text-gray-900">到 PaaS 開通訂閱</h2>
          <p class="mt-1 text-sm leading-6 text-gray-600">在 PaaS 選擇工作區與方案，建立安全存取服務。費用與付款都會在 PaaS 確認；這裡不會自動扣款。</p>
          <div class="mt-3 rounded-xl bg-orange-50 px-4 py-3 text-sm leading-6 text-orange-900">
            <p class="font-semibold">一台 HA、一個人登入：選 1 組路由 ＋ 1 個 Access 席次。</p>
            <p class="mt-1">路由是對外網址的數量；席次是允許登入的人數。選「不加購」沒有登入席次，無法完成本頁的安全連結。多人使用時，請依不同 Email 的人數加購。</p>
          </div>
          <a :href="bootstrap?.portal_url || portalFallback" target="_blank" rel="noopener noreferrer" class="mt-4 inline-flex rounded-lg bg-cf-orange px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-600">前往 PaaS 開通 ↗</a>
          <p class="mt-3 text-xs text-gray-500">已經開通了？繼續下方的帳戶授權，就能選擇現有服務。</p>
        </div>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-7">
      <div class="flex items-start gap-4">
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-100 font-bold text-cf-orange">2</span>
        <div class="min-w-0 flex-1">
          <h2 class="text-lg font-semibold text-gray-900">授權這個 add-on</h2>
          <p class="mt-1 text-sm leading-6 text-gray-600">按下按鈕後到 PaaS 輸入短碼並同意授權。這個頁面不會要求你貼 Tunnel token。</p>
          <div v-if="bootstrap?.authorized" class="mt-4 flex flex-wrap items-center gap-3">
            <span class="inline-flex rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800">✓ PaaS 帳戶已連接</span>
            <button v-if="!bootstrap.connection && !bootstrap.release_pending" class="text-xs font-semibold text-gray-600 underline" @click="revokeAuthorization">撤銷帳戶授權</button>
          </div>
          <div v-else class="mt-4 space-y-4">
            <button :disabled="busy" class="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50" @click="beginAuthorization">取得授權短碼</button>
            <div v-if="authorization" class="rounded-xl border border-blue-200 bg-blue-50 p-5">
              <p class="text-sm font-medium text-blue-900">在 PaaS 頁面輸入這組短碼</p>
              <p class="mt-2 select-all font-mono text-2xl font-bold tracking-widest text-slate-900">{{ authorization.user_code }}</p>
              <a :href="authorization.verification_url" target="_blank" rel="noopener noreferrer" class="mt-3 inline-block rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800">開啟授權頁 ↗</a>
              <p class="mt-3 text-xs text-blue-700">{{ authStatus === 'waiting' ? '等待 PaaS 核准，這裡會自動更新。' : '授權有效時間約 15 分鐘。' }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-7" :class="!bootstrap?.authorized ? 'opacity-70' : ''">
      <div class="flex items-start gap-4">
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-100 font-bold text-cf-orange">3</span>
        <div class="min-w-0 flex-1">
          <h2 class="text-lg font-semibold text-gray-900">選服務，確認每個網址有保護</h2>
          <p class="mt-1 text-sm leading-6 text-gray-600">先在 PaaS 的「應用路由」新增網址，再到「存取控制」設定允許登入的人。回到這裡選擇該服務。</p>
          <details class="mt-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <summary class="cursor-pointer font-semibold">HA 的內部網址要填什麼？出現 400 或 502 怎麼辦？</summary>
            <p class="mt-3 leading-6">先到 HA「設定 → 系統 → 網路」確認 HTTP 埠。新版 HAOS 通常填 <code>http://homeassistant:80</code>；使用 8123 埠的安裝則填 <code>http://homeassistant:8123</code>。請以這台 HA 的實際設定為準。</p>
            <p class="mt-2 leading-6">502 通常要檢查內部位址、埠與服務是否啟動。若 HA 回 400，檢查 HA 日誌是否拒絕反向代理；在 HTTP 設定啟用 Trust X-Forwarded-For，並把此 add-on 的代理 IP 加入 Trusted proxies，再確認重啟後的設定。</p>
            <a href="https://www.home-assistant.io/integrations/http/#reverse-proxies" target="_blank" rel="noopener noreferrer" class="mt-2 inline-block font-semibold text-cf-orange underline">HA 官方反向代理設定說明 ↗</a>
          </details>
          <template v-if="bootstrap?.authorized">
            <button :disabled="busy" class="mt-4 rounded-lg border border-cf-orange bg-orange-50 px-4 py-2 text-sm font-semibold text-cf-orange hover:bg-orange-100 disabled:opacity-50" @click="refreshServices">我已在 PaaS 完成，重新讀取服務</button>
            <div class="mt-5 grid gap-3 sm:grid-cols-2">
              <label class="text-sm font-medium text-gray-700">工作區
                <select v-model="workspaceId" class="mt-2 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm" @change="onWorkspaceChange">
                  <option :value="null">請選擇工作區</option>
                  <option v-for="workspace in workspaces" :key="workspace.id" :value="workspace.id">{{ workspace.name }}</option>
                </select>
              </label>
              <label class="text-sm font-medium text-gray-700">安全存取服務
                <select v-model="accessId" :disabled="!workspaceId" class="mt-2 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm disabled:bg-gray-100" @change="loadReview">
                  <option :value="null">請選擇服務</option>
                  <option v-for="access in accesses" :key="access.id" :value="access.id">{{ access.name }} · {{ serviceLabel(access.state) }}</option>
                </select>
              </label>
            </div>
            <div v-if="workspaceId && !accesses.length" class="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">這個工作區還沒有安全存取服務。<a :href="workspacePortal" target="_blank" rel="noopener noreferrer" class="font-semibold underline">到 PaaS 建立 ↗</a></div>
            <div v-if="review" class="mt-5 rounded-xl border p-5" :class="review.ready ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 class="font-semibold text-gray-900">{{ review.access.name }} · {{ review.ready ? '可以連結' : '需要完成設定' }}</h3>
                <button class="text-xs font-semibold text-slate-700 underline" @click="loadReview">重新檢查</button>
              </div>
              <p class="mt-2 text-xs text-gray-600">訂閱：{{ review.access.subscription?.plan_name || '尚未訂閱' }}（{{ subscriptionLabel(review.access.subscription?.state) }}） · 服務：{{ serviceLabel(review.access.state) }} · 綁定：{{ bindingLabel(review.access.binding_state) }}</p>
              <p v-if="review.access.subscription?.ac_max_access_seats != null" class="mt-2 text-xs text-gray-600">Access 席次：已使用 {{ review.access.subscription.ac_used_access_seats ?? '—' }} / {{ review.access.subscription.ac_max_access_seats }} 席。同一個 Email 用於多個網址只計 1 席。</p>
              <div v-for="route in review.access.routes" :key="route.hostname" class="mt-3 rounded-lg bg-white px-4 py-3 text-sm text-gray-700">
                <span :class="route.protected ? 'text-emerald-700' : 'text-red-700'" class="font-bold">{{ route.protected ? '✓' : '!' }}</span>
                <span class="ml-2 font-medium">{{ route.hostname }}</span>
                <span class="ml-2 text-xs text-gray-500">{{ route.protected ? '保護設定已確認' : '保護設定未完成' }}</span>
              </div>
              <ul v-if="review.issues.length" class="mt-4 list-inside list-disc space-y-1 text-sm text-amber-900"><li v-for="issue in review.issues" :key="issue">{{ issue }}</li></ul>
              <div class="mt-4 flex flex-wrap gap-3 text-sm font-semibold">
                <a :href="review.portal_routes_url" target="_blank" rel="noopener noreferrer" class="text-cf-orange underline">設定應用路由 ↗</a>
                <a :href="review.portal_access_url" target="_blank" rel="noopener noreferrer" class="text-cf-orange underline">設定 Access 保護 ↗</a>
              </div>
            </div>
          </template>
        </div>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm sm:p-7">
      <div class="flex items-start gap-4">
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-100 font-bold text-cf-orange">4</span>
        <div class="min-w-0 flex-1">
          <h2 class="text-lg font-semibold text-gray-900">連結並啟用</h2>
          <p class="mt-1 text-sm leading-6 text-gray-600">按下前系統會再檢查一次所有網址。通過後才取得 Tunnel 憑證，綁定這台裝置並重新啟動 add-on。</p>
          <button :disabled="!review?.ready || busy" class="mt-4 rounded-lg bg-cf-orange px-5 py-2.5 text-sm font-semibold text-white shadow-sm disabled:cursor-not-allowed disabled:bg-gray-300" @click="connect">{{ busy ? '處理中…' : '連結並啟用' }}</button>
          <p v-if="bootstrap?.connection && !bootstrap.release_pending" class="mt-4 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">✓ 已連結 {{ bootstrap.connection.name }}。add-on 重新啟動後可到 Dashboard 查看 Tunnel 狀態。</p>
          <div v-if="bootstrap?.release_pending" class="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            遠端綁定尚未確認解除。若剛按下停止，請等 add-on 重啟及 Tunnel 停止；系統會自動重試。
            <button class="ml-2 font-semibold underline" @click="finishDisconnect">重新嘗試解除綁定</button>
          </div>
          <div v-if="bootstrap?.connection" class="mt-4 flex flex-wrap items-center gap-3">
            <button class="rounded-lg border border-gray-300 bg-white px-4 py-2 text-xs font-semibold text-gray-700 hover:bg-gray-50" @click="loadStatus(false)">刷新連線狀態</button>
            <button class="rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 text-xs font-semibold text-blue-800 hover:bg-blue-100" @click="checkExternal">測試外部網址</button>
            <button v-if="!bootstrap.release_pending" class="text-xs font-semibold text-red-700 underline" @click="disconnect">停止本機連線並解除綁定</button>
            <button v-else class="text-xs font-semibold text-amber-800 underline" @click="finishDisconnect">檢查並完成遠端解除綁定</button>
          </div>
          <div v-if="connectionStatus?.connected" class="mt-4 grid gap-3 sm:grid-cols-3">
            <div class="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm"><p class="text-xs text-gray-500">訂閱</p><p class="mt-1 font-semibold text-gray-900">{{ subscriptionLabel(connectionStatus.subscription?.state) }}</p></div>
            <div class="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm"><p class="text-xs text-gray-500">Access 保護</p><p class="mt-1 font-semibold" :class="connectionStatus.access_ready ? 'text-emerald-700' : 'text-red-700'">{{ connectionStatus.access_ready ? '設定已確認' : '需要修復' }}</p></div>
            <div class="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm"><p class="text-xs text-gray-500">Tunnel</p><p class="mt-1 font-semibold text-gray-900">{{ tunnelLabel(connectionStatus.tunnel_status) }}</p></div>
            <p class="sm:col-span-3 text-xs text-gray-500">檢查時間：{{ new Date(connectionStatus.checked_at * 1000).toLocaleString() }}。{{ connectionStatus.external.length ? '匿名外部探測只確認回應，不代表指定使用者登入成功。' : '外部網址尚未獨立測試；Tunnel 在線不等於公開網址可用。' }}</p>
            <div v-for="result in connectionStatus.external" :key="result.hostname" class="rounded-xl border border-gray-200 bg-white p-4 text-sm">
              <p class="font-medium text-gray-900">{{ result.hostname }}</p>
              <p class="mt-1 text-xs" :class="result.status === 'login_required' ? 'text-emerald-700' : result.status === 'public_response' ? 'text-red-700' : 'text-amber-700'">{{ externalLabel(result.status) }}</p>
            </div>
            <ul v-if="connectionStatus.issues.length" class="sm:col-span-3 list-inside list-disc text-sm text-red-700"><li v-for="issue in connectionStatus.issues" :key="issue">{{ issue }}</li></ul>
          </div>
          <p class="mt-3 text-xs text-gray-500">Tunnel 連線成功只代表通道在線；公開網址與登入保護的外部驗證仍需個別確認。</p>
        </div>
      </div>
    </section>
    <section class="rounded-2xl border border-slate-200 bg-slate-50 p-6 text-sm text-slate-700">
      <h2 class="font-semibold text-slate-900">刪除路由或取消訂閱時</h2>
      <p class="mt-2 leading-6">此頁解除綁定只會停止這台 add-on 並釋放 PaaS 的裝置綁定。請回 PaaS 的應用路由或服務頁完成 DNS、Access 與訂閱清理；本頁不會把「已解除綁定」誤當成「公開網址已刪除」。</p>
      <a :href="review?.portal_routes_url || workspacePortal" target="_blank" rel="noopener noreferrer" class="mt-3 inline-block font-semibold text-cf-orange underline">前往 PaaS 管理路由 ↗</a>
    </section>
    <p class="text-center text-xs text-gray-500">自行管理 Cloudflare？<router-link to="/setup" class="font-semibold text-cf-orange underline">前往 Local 模式設定</router-link></p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '@/api'

interface Connection { access_id: number; workspace_id: number; name: string }
interface Bootstrap { authorized: boolean; portal_url: string; connection: Connection | null; release_pending: boolean }
interface Workspace { id: number; name: string; portal_url: string }
interface Access { id: number; name: string; state: string }
interface Review { ready: boolean; issues: string[]; access: { id: number; name: string; state: string; binding_state: string; subscription: { state: string; plan_name: string; ac_max_access_seats?: number | null; ac_used_access_seats?: number | null } | null; routes: { hostname: string; protected: boolean }[] }; portal_access_url: string; portal_routes_url: string }
interface Authorization { user_code: string; verification_url: string; interval: number }
interface ConnectionStatus { connected: boolean; subscription: { state: string } | null; access_ready: boolean; issues: string[]; tunnel_status: string; checked_at: number; external: { hostname: string; status: string; http_status?: number }[] }

const steps = ['開通訂閱', '授權帳戶', '檢查保護', '連結啟用']
const portalFallback = 'https://aiot.woowtech.io/woow#/workspaces'
const bootstrap = ref<Bootstrap | null>(null)
const authorization = ref<Authorization | null>(null)
const authStatus = ref('')
const workspaces = ref<Workspace[]>([])
const accesses = ref<Access[]>([])
const workspaceId = ref<number | null>(null)
const accessId = ref<number | null>(null)
const review = ref<Review | null>(null)
const connectionStatus = ref<ConnectionStatus | null>(null)
const busy = ref(false)
const error = ref('')
const message = ref('')
let authTimer: ReturnType<typeof setTimeout> | undefined
const workspacePortal = computed(() => workspaces.value.find((item) => item.id === workspaceId.value)?.portal_url || portalFallback)

function label(value: string | undefined, names: Record<string, string>): string {
  return value ? (names[value] || `待確認（${value}）`) : '無法確認'
}

function serviceLabel(value: string): string {
  return label(value, { pending: '待建立', provisioning: '建立中', active: '已啟用', active_no_route: '已啟用，尚無網址', error: '設定錯誤', suspended: '已停權', deleting: '刪除中' })
}

function subscriptionLabel(value?: string): string {
  return label(value, { in_progress: '有效', draft: '待開通', paused: '已暫停', closed: '已結束', cancel: '已取消' })
}

function bindingLabel(value: string): string {
  return label(value, { unbound: '尚未綁定', claimed: '已綁定一台裝置', legacy: '舊版綁定，需檢查' })
}

function tunnelLabel(value: string): string {
  return label(value, { running: '在線', starting: '啟動中', stopped: '未運行' })
}

async function loadBootstrap() {
  bootstrap.value = await api<Bootstrap>('api/paas/bootstrap')
  if (bootstrap.value.authorized) {
    await loadWorkspaces()
    if (bootstrap.value.connection) {
      workspaceId.value = bootstrap.value.connection.workspace_id
      await onWorkspaceChange()
      accessId.value = bootstrap.value.connection.access_id
      await loadReview()
      await loadStatus()
    }
  }
}

async function loadWorkspaces() {
  workspaces.value = (await api<{ workspaces: Workspace[] }>('api/paas/workspaces')).workspaces
}

async function refreshServices() {
  busy.value = true
  error.value = ''
  try {
    const previousWorkspace = workspaceId.value
    const previousAccess = accessId.value
    await loadWorkspaces()
    workspaceId.value = workspaces.value.some((item) => item.id === previousWorkspace) ? previousWorkspace : null
    await onWorkspaceChange()
    if (accesses.value.some((item) => item.id === previousAccess)) {
      accessId.value = previousAccess
      await loadReview()
    }
    if (!error.value) message.value = '服務列表已更新。請選擇服務，確認保護設定後再連結。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '暫時無法更新服務列表'
  } finally {
    busy.value = false
  }
}

async function onWorkspaceChange() {
  review.value = null
  accessId.value = null
  accesses.value = []
  if (workspaceId.value !== null) {
    accesses.value = (await api<{ accesses: Access[] }>(`api/paas/workspaces/${workspaceId.value}/accesses`)).accesses
  }
}

async function loadReview() {
  review.value = null
  if (accessId.value === null) return
  try {
    review.value = await api<Review>(`api/paas/accesses/${accessId.value}/review`)
    error.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法檢查服務'
  }
}

async function beginAuthorization() {
  busy.value = true
  error.value = ''
  if (authTimer) clearTimeout(authTimer)
  try {
    authorization.value = await api<Authorization>('api/paas/authorization', { method: 'POST' })
    authStatus.value = 'waiting'
    authTimer = setTimeout(pollAuthorization, authorization.value.interval * 1000)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法開始授權'
  } finally {
    busy.value = false
  }
}

async function pollAuthorization() {
  try {
    const result = await api<{ status: string; interval?: number }>('api/paas/authorization/status')
    authStatus.value = result.status
    if (result.status === 'authorized') {
      authorization.value = null
      await loadBootstrap()
      message.value = 'PaaS 帳戶已授權。現在選擇工作區與安全存取服務。'
      return
    }
    if (result.status === 'waiting') {
      authTimer = setTimeout(pollAuthorization, (result.interval || authorization.value?.interval || 5) * 1000)
      return
    }
    error.value = result.status === 'denied' ? '授權被拒絕。請重新取得短碼。' : '授權已逾時。請重新取得短碼。'
    authorization.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '授權狀態暫時無法確認'
    authTimer = setTimeout(pollAuthorization, 10000)
  }
}

async function connect() {
  if (accessId.value === null || !review.value?.ready) return
  busy.value = true
  error.value = ''
  try {
    await api(`api/paas/accesses/${accessId.value}/connect`, { method: 'POST' })
    message.value = '已儲存連結，add-on 正在重新啟動。請稍後刷新狀態。'
    try { await loadBootstrap() } catch { /* Restart briefly interrupts Ingress. */ }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '連結失敗'
    await loadReview()
  } finally {
    busy.value = false
  }
}

async function loadStatus(probe = false) {
  try {
    connectionStatus.value = await api<ConnectionStatus>(`api/paas/connection/status${probe ? '?probe=true' : ''}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法讀取連線狀態'
  }
}

async function checkExternal() {
  message.value = '正在從 add-on 網路檢查公開網址…'
  await loadStatus(true)
  message.value = ''
}

function externalLabel(status: string): string {
  const labels: Record<string, string> = {
    login_required: '匿名訪問進入 Cloudflare Access 登入流程',
    public_response: '匿名訪問直接得到 200；請立即檢查 Access 保護',
    blocked_or_protected: 'HTTP 403：可能被 Access 或其他規則封鎖，無法單獨判定',
    origin_error: '來源服務或 Tunnel 回傳錯誤',
    blocked_private_address: '網址解析到私有/保留位址，已取消探測',
    unreachable: 'DNS、TLS 或網路連線失敗',
    undetermined: '回應無法判定，請到 PaaS 與瀏覽器再驗證',
  }
  return labels[status] || '無法判定'
}

async function disconnect() {
  if (!window.confirm('將停止這台裝置的 PaaS Tunnel，接著解除遠端綁定。要繼續嗎？')) return
  error.value = ''
  try {
    await api('api/paas/disconnect', { method: 'POST' })
    message.value = '本機連線停止中。add-on 重啟後會嘗試解除遠端綁定。'
    if (bootstrap.value) bootstrap.value.release_pending = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法停止連線'
  }
}

async function finishDisconnect() {
  error.value = ''
  try {
    await api('api/paas/disconnect/finish', { method: 'POST' })
    message.value = '本機連線與遠端綁定均已解除。'
    connectionStatus.value = null
    await loadBootstrap()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '遠端解除綁定尚未完成；請稍後重試或到 PaaS 處理'
  }
}

async function revokeAuthorization() {
  error.value = ''
  try {
    await api('api/paas/authorization/revoke', { method: 'POST' })
    workspaces.value = []
    accesses.value = []
    review.value = null
    workspaceId.value = null
    accessId.value = null
    await loadBootstrap()
    message.value = 'PaaS 帳戶授權已撤銷。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '撤銷授權失敗'
  }
}

onMounted(() => { loadBootstrap().catch((cause) => { error.value = cause instanceof Error ? cause.message : '無法讀取 PaaS 狀態' }) })
onUnmounted(() => { if (authTimer) clearTimeout(authTimer) })
</script>
