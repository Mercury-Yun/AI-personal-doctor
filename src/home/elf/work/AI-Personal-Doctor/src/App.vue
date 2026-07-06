<template>
  <div class="kiosk-app" :class="{ 'mobile-mode': isMobileView }">
    <header v-if="isMobileView && route.path !== '/family'" class="topbar">
      <div class="brand">
        <span class="brand-icon">🤖</span>
        <strong>AI健康助手</strong>
      </div>
      <nav class="topnav">
        <RouterLink v-for="item in navItemsMobile" :key="item.to" :to="item.to">{{ item.label }}</RouterLink>
      </nav>
    </header>
    <main class="page-view">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWakeController } from './composables/useWakeController'
import { useWakeStore } from './stores/wake'
import { useVoiceSessionStore } from './stores/voiceSession'
import { bindMobileView, isMobileView as checkMobileView } from './utils/mobileView'
import { getVoiceSessionBusy, syncVoiceSessionBusy, voiceSessionStatusLabel, VOICE_BUSY_EVENT } from './utils/voiceSession'

const route = useRoute()
const router = useRouter()
const wakeCtl = useWakeController()
const wakeStore = useWakeStore()
const voiceSessionStore = useVoiceSessionStore()

const navItemsMobile = [
  { to: '/family', label: '首页' },
  { to: '/profiles', label: '档案' },
  { to: '/records', label: '病例' },
  { to: '/medications', label: '药物' },
  { to: '/reminders', label: '提醒' },
]

const isMobileView = ref(false)
let unbindMobileView = null

// 子页面兼容 inject
provide('wakeSessionInFlight', computed(() => wakeStore.sessionInFlight))
provide('wakeListening', computed(() => wakeStore.listening))

const voiceSessionLabel = computed(() => voiceSessionStatusLabel(voiceSessionStore.busyType))

const wakeHint = computed(() => {
  if (voiceSessionLabel.value) return ''
  if (wakeStore.listening) return `请说「${wakeStore.word}」唤醒…`
  if (wakeStore.error && wakeStore.enabled) return wakeStore.error
  return ''
})

const wakeToggleLabel = computed(() => {
  if (!wakeStore.enabled) return '唤醒关'
  if (wakeStore.listening) return `听「${wakeStore.word}」中`
  if (wakeStore.available === null || wakeCtl.getVoiceOnline() === null) return '检测中…'
  if (wakeStore.available === false) return '唤醒不可用'
  if (wakeCtl.getVoiceOnline() === false) return '语音离线'
  if (voiceSessionStore.busyType) return '会话进行中'
  if (!wakeCtl.isIdleRoute()) return '本页不监听'
  return `等「${wakeStore.word}」`
})

const syncVoiceBusy = () => {
  const busy = getVoiceSessionBusy()
  voiceSessionStore.setBusy(busy === 'doctor' || busy === 'photo' ? busy : null)
}

const retryWake = async () => {
  wakeStore.setAvailable(null)
  wakeStore.setError('')
  await wakeCtl.refreshHealth()
  if (wakeStore.enabled) wakeCtl.ensureLoop()
}

const syncMobileView = () => {
  isMobileView.value = checkMobileView()
}

onMounted(async () => {
  syncMobileView()
  unbindMobileView = bindMobileView((mobile) => {
    isMobileView.value = mobile
  })
  if (!isMobileView.value && localStorage.getItem('wake_enabled') !== '0') {
    wakeStore.setEnabled(true)
  }
  syncVoiceBusy()
  window.addEventListener(VOICE_BUSY_EVENT, syncVoiceBusy)
  wakeCtl.bind(router, route)
  await wakeCtl.boot()
})

onUnmounted(() => {
  wakeCtl.shutdown()
  if (unbindMobileView) unbindMobileView()
  window.removeEventListener(VOICE_BUSY_EVENT, syncVoiceBusy)
})

watch(
  () => route.path,
  (path) => {
    wakeCtl.onRouteChange(path)
    syncVoiceBusy()
  }
)

watch(
  () => voiceSessionStore.busyType,
  (busy) => {
    wakeCtl.onVoiceBusyChanged(Boolean(busy))
  }
)
</script>
