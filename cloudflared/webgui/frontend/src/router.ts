import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from '@/pages/Dashboard.vue'
import Config from '@/pages/Config.vue'
import Logs from '@/pages/Logs.vue'
import SetupWizard from '@/pages/SetupWizard.vue'
import PaasLink from '@/pages/PaasLink.vue'

const routes = [
  { path: '/', name: 'dashboard', component: Dashboard },
  { path: '/setup', name: 'setup', component: SetupWizard },
  { path: '/paas', name: 'paas', component: PaasLink },
  { path: '/config', name: 'config', component: Config },
  { path: '/logs', name: 'logs', component: Logs },
]

export default createRouter({
  // Hash history keeps routing fully client-side, so the app works under
  // the dynamic Home Assistant Ingress path prefix without configuration.
  history: createWebHashHistory(),
  routes,
})
