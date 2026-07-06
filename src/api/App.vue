<template>
  <div class="kiosk-app">
    <header class="topbar">
      <div class="brand">
        <span class="brand-icon">+</span>
        <strong>AI医生</strong>
      </div>
      <nav class="topnav">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to">{{ item.label }}</RouterLink>
      </nav>
      <div class="topbar-meta">
        <button
          v-if="wakeEnabled"
          class="wake-toggle"
          :class="{ active: wakeEnabled, listening: wakeArmed && !voiceSessionLabel }"
          type="button"
          @click="toggleWake"
        >
          {{ wakeToggleLabel }}
        </button>
        <span v-if="voiceSessionLabel" class="voice-session-pill">{{ voiceSessionLabel }}</span>
        <span v-else-if="wakeArmed" class="wake-listening">等待「{{ wakeWord }}」…</span>
        <span v-else-if="wakeEnabled && wakePauseReason" class="wake-paused">{{ wakePauseReason }}</span>
        <span class="voice-pill" :class="voiceStatusClass">
          {{ voiceStatusText }}
        </span>
        <span class="clock">{{ clockText }}</span>
      </div>
    </header>
    <main class="page-view">
      <RouterView />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { cancelWakeSession, getDeviceStatus, getWakeInfo, pauseWakeListening, resumeWakeListening, wakeSession } from './api/device'
import { emitVoiceStop, getVoiceSessionBusy, quickPreparePhotoCapture, releaseVoiceSession, syncVoiceSessionBusy, voiceSessionStatusLabel, VOICE_BUSY_EVENT } from './utils/voiceSession'

const router = useRouter()
const route = useRoute()

/** 仅在这些页面跑全局「等豆包」循环，避免与问诊/问药页按钮抢麦克风 */
const WAKE_IDLE_ROUTES = new Set(['/dashboard', '/device', '/profiles', '/records', '/medications', '/reminders', '/'])
const VOICE_PAGE_ROUTES = new Set(['/doctor-chat', '/photo-medicine'])

/** 语音问诊/问药进行中时暂停全局唤醒；问诊/问药页空闲时不跑唤醒循环 */
const isPhotoHandoffPending = () => {
  const handoff = sessionStorage.getItem('photo_session_handoff')
  if (!handoff) return false
  const age = Date.now() - Number(handoff)
  if (route.path !== '/photo-medicine' && age > 8000) return false
  return age < 180000
}

const clearStaleVoiceSessionOnIdleRoute = () => {
  if (!WAKE_IDLE_ROUTES.has(route.path)) return
  const handoff = sessionStorage.getItem('photo_session_handoff')
  if (handoff && route.path !== '/photo-medicine' && Date.now() - Number(handoff) > 8000) {
    sessionStorage.removeItem('photo_session_handoff')
    sessionStorage.removeItem('wake_photo_payload')
  }
  if (getVoiceSessionBusy() && route.path !== '/photo-medicine' && route.path !== '/doctor-chat') {
    syncVoiceSessionBusy(null)
  }
  sessionStorage.removeItem('wake_chat_payload')
}

const armWakeOnIdleRoute = () => {
  if (armWakeTimer) {
    window.clearTimeout(armWakeTimer)
  }
  armWakeTimer = window.setTimeout(async () => {
    armWakeTimer = null
    clearStaleVoiceSessionOnIdleRoute()
    refreshVoiceSessionBusy()
    wakePauseReason.value = ''
    await resumeWakeListening().catch(() => {})
    await sleep(300)
    if (wakeEnabled.value && WAKE_IDLE_ROUTES.has(route.path)) {
      wakeLoop()
    }
  }, 400)
}

const canRunWakeSession = () =>
  WAKE_IDLE_ROUTES.has(route.path) &&
  !voiceSessionBusyType.value &&
  !isPhotoHandoffPending() &&
  route.path !== '/photo-medicine'

const navItems = [
  { to: '/dashboard', label: '首页' },
  { to: '/doctor-chat', label: '问诊' },
  { to: '/photo-medicine', label: '拍照问药' },
  { to: '/profiles', label: '档案' },
  { to: '/records', label: '病例' },
  { to: '/medications', label: '药物' },
  { to: '/reminders', label: '提醒' },
  { to: '/device', label: '语音' },
]

const voiceOnline = ref(null)
const demoBusy = ref(false)
const captureActive = ref(false)
const clockText = ref('')
const wakeEnabled = ref(localStorage.getItem('wake_enabled') !== '0')
const wakeAvailable = ref(null)
const wakeInfoError = ref('')
const wakeListening = ref(false)
const wakeSessionInFlight = ref(false)
const wakeWord = ref('豆包')
const wakePauseReason = ref('')
const voiceSessionBusyType = ref(getVoiceSessionBusy())
const ttsBusy = ref(false)
let clockTimer = null
let statusTimer = null
let wakeLoopRunning = false
let offlineStreak = 0
let wakeOfflineStreak = 0
let wakeAbortController = null
let armWakeTimer = null

const abortWakeRequest = async (syncBackend = false) => {
  if (wakeAbortController) {
    wakeAbortController.abort()
    wakeAbortController = null
  }
  if (syncBackend) {
    await cancelWakeSession().catch(() => {})
  }
}

const stopGlobalWakeListen = async () => {
  await abortWakeRequest(true)
  wakeListening.value = false
  wakeSessionInFlight.value = false
}

const wakeArmed = computed(() => {
  if (!wakeEnabled.value || wakeAvailable.value !== true || voiceOnline.value !== true) return false
  if (voiceSessionBusyType.value) return false
  return WAKE_IDLE_ROUTES.has(route.path)
})

const voiceStatusText = computed(() => {
  if (voiceOnline.value === null) return '检测中'
  if (captureActive.value && voiceOnline.value) return '拍照中'
  return voiceOnline.value ? '在线' : '离线'
})

const voiceStatusClass = computed(() => {
  if (voiceOnline.value === null) return 'checking'
  if (captureActive.value && voiceOnline.value) return 'busy'
  return voiceOnline.value ? 'online' : 'offline'
})

provide('wakeListening', wakeListening)
provide('wakeSessionInFlight', wakeSessionInFlight)

const voiceSessionLabel = computed(() => voiceSessionStatusLabel(voiceSessionBusyType.value))

const refreshVoiceSessionBusy = () => {
  voiceSessionBusyType.value = getVoiceSessionBusy()
}

const wakeToggleLabel = computed(() => {
  if (!wakeEnabled.value) return '唤醒关'
  if (wakeAvailable.value === null || voiceOnline.value === null) return '检测中…'
  if (!wakeAvailable.value) return '唤醒不可用'
  if (!voiceOnline.value) return '语音离线'
  if (voiceSessionBusyType.value) return '会话进行中'
  if (!WAKE_IDLE_ROUTES.has(route.path)) return '本页不监听'
  if (wakeListening.value) return '正在听…'
  return '唤醒开'
})

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const tickClock = () => {
  clockText.value = new Date().toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const shouldHoldVoiceOnline = () =>
  wakeSessionInFlight.value || wakeListening.value || ttsBusy.value || Boolean(voiceSessionBusyType.value)

const refreshVoiceStatus = async () => {
  try {
    const { data } = await getDeviceStatus()
    ttsBusy.value = Boolean(data.tts_busy || data.tts_playing)
    demoBusy.value = Boolean(data.demo_busy)
    captureActive.value = Boolean(data.capture_active)
    if (data.online) {
      voiceOnline.value = true
      offlineStreak = 0
      return true
    }
    if (shouldHoldVoiceOnline() && voiceOnline.value === true) {
      return true
    }
    offlineStreak += 1
    if (offlineStreak >= 6 || voiceOnline.value === null) {
      voiceOnline.value = false
    }
    return false
  } catch {
    if (shouldHoldVoiceOnline() && voiceOnline.value === true) {
      return true
    }
    offlineStreak += 1
    if (offlineStreak >= 6 || voiceOnline.value === null) {
      voiceOnline.value = false
    }
    return false
  }
}

const refreshWakeInfo = async () => {
  if (wakeSessionInFlight.value) {
    return wakeAvailable.value !== false
  }
  try {
    const { data } = await getWakeInfo()
    if (data.enabled && data.kws_enabled) {
      wakeOfflineStreak = 0
      wakeAvailable.value = true
      wakeInfoError.value = captureActive.value ? '正在拍照，请稍候…' : ''
      wakeWord.value = data.wake_word || '豆包'
      return true
    }
    if (captureActive.value && voiceOnline.value === true) {
      wakeOfflineStreak = 0
      wakeAvailable.value = true
      wakeInfoError.value = '正在拍照，请稍候…'
      wakeWord.value = data.wake_word || '豆包'
      return true
    }
    wakeInfoError.value = data.error || '唤醒未就绪'
    wakeWord.value = data.wake_word || '豆包'
    if (shouldHoldVoiceOnline() && wakeAvailable.value === true) {
      return true
    }
    wakeOfflineStreak += 1
    if (wakeOfflineStreak >= 6 || wakeAvailable.value === null) {
      wakeAvailable.value = false
      if (wakeEnabled.value) {
        wakeListening.value = false
      }
    }
    return wakeAvailable.value === true
  } catch (error) {
    if (shouldHoldVoiceOnline() && wakeAvailable.value === true) {
      return true
    }
    wakeOfflineStreak += 1
    wakeInfoError.value = error?.response?.data?.detail || error?.message || '无法连接语音服务'
    if (wakeOfflineStreak >= 6 || wakeAvailable.value === null) {
      wakeAvailable.value = false
    }
    return false
  }
}

const refreshVoiceHealth = async () => {
  await Promise.all([refreshVoiceStatus(), refreshWakeInfo()])
}

const refreshVoiceHealthWithRetry = async (attempts = 4) => {
  for (let i = 0; i < attempts; i += 1) {
    const [onlineOk, wakeOk] = await Promise.all([refreshVoiceStatus(), refreshWakeInfo()])
    if (onlineOk && wakeOk) return true
    if (i < attempts - 1) {
      await sleep(800 * (i + 1))
    }
  }
  return false
}

const handleWakeResult = async (payload) => {
  wakeListening.value = false
  const body = JSON.stringify(payload)

  if (payload.intent === 'photo' && payload.text) {
    syncVoiceSessionBusy('photo')
    sessionStorage.setItem('photo_session_handoff', String(Date.now()))
    const body = JSON.stringify({
      ...payload,
      fast_handoff: true,
      voice_prep_done: true,
    })
    sessionStorage.setItem('wake_photo_payload', body)
    await pauseWakeListening(120).catch(() => {})
    await cancelWakeSession().catch(() => {})
    await quickPreparePhotoCapture({ voicePrepDone: true })
    if (route.path === '/photo-medicine') {
      window.dispatchEvent(new CustomEvent('app-wake-photo', { detail: JSON.parse(body) }))
      return
    }
    await router.push('/photo-medicine')
    return
  }

  syncVoiceSessionBusy('doctor')
  sessionStorage.setItem('wake_chat_payload', body)
  if (route.path === '/doctor-chat') {
    window.dispatchEvent(new CustomEvent('app-wake-chat', { detail: payload }))
    return
  }
  await router.push('/doctor-chat')
}

const wakeLoop = async () => {
  if (wakeLoopRunning) return
  wakeLoopRunning = true
  while (wakeEnabled.value) {
    wakePauseReason.value = ''
    if (wakeAvailable.value !== true) {
      wakePauseReason.value = wakeInfoError.value || '唤醒未就绪，语音引擎加载中'
      wakeListening.value = false
      if (!wakeSessionInFlight.value) {
        await refreshWakeInfo()
      }
      await sleep(1500)
      continue
    }
    if (voiceOnline.value !== true) {
      if (captureActive.value) {
        wakePauseReason.value = '正在拍照，请稍候…'
      } else {
        wakePauseReason.value = '语音离线，正在重连…'
      }
      wakeListening.value = false
      await refreshVoiceStatus()
      await sleep(1500)
      continue
    }
    if (!canRunWakeSession()) {
      if (ttsBusy.value && WAKE_IDLE_ROUTES.has(route.path) && !voiceSessionBusyType.value) {
        wakePauseReason.value = '播报中，可说「豆包」打断'
      } else if (ttsBusy.value) {
        wakePauseReason.value = '播报中，请稍候…'
      } else if (voiceSessionBusyType.value) {
        wakePauseReason.value = route.path === '/photo-medicine' ? '问药进行中' : route.path === '/doctor-chat' ? '问诊进行中' : '语音会话进行中'
      } else if (VOICE_PAGE_ROUTES.has(route.path)) {
        wakePauseReason.value = '本页请用下方按钮'
      } else {
        wakePauseReason.value = ''
      }
      wakeListening.value = false
      await refreshVoiceStatus()
      await sleep(ttsBusy.value ? 500 : 1500)
      continue
    }
    await resumeWakeListening().catch(() => {})
    wakeListening.value = true
    wakeSessionInFlight.value = true
    wakeAbortController = new AbortController()
    const wakeSignal = wakeAbortController.signal
    try {
      const { data } = await wakeSession({ signal: wakeSignal })
      if (!WAKE_IDLE_ROUTES.has(route.path)) {
        continue
      }
      await handleWakeResult(data)
    } catch (error) {
      if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError') {
        continue
      }
      const status = error?.response?.status
      if (status === 499) {
        continue
      }
      if (status === 408) {
        wakePauseReason.value = '未听到唤醒词，请再说豆包'
      } else if (
        error?.code === 'ECONNABORTED' ||
        /timeout/i.test(String(error?.message || ''))
      ) {
        wakePauseReason.value = '未听到唤醒词，请再说豆包'
      } else if (status === 409) {
        await abortWakeRequest(false)
        wakePauseReason.value = '正在重新听唤醒词…'
        await sleep(1200)
      } else if (status === 400) {
        wakePauseReason.value = error?.response?.data?.detail || '唤醒失败，请稍后再试'
        await sleep(2000)
      } else if (status === 503) {
        const detail = String(error?.response?.data?.detail || '')
        wakePauseReason.value = detail.includes('繁忙') || detail.includes('拍照') || detail.includes('提醒')
          ? detail
          : '语音服务未就绪，稍后自动重试'
        const waitMs = detail.includes('重启') || detail.includes('未就绪') || detail.includes('离线') ? 4000 : 2000
        await sleep(waitMs)
      } else {
        wakePauseReason.value = '唤醒异常，稍后重试'
        await sleep(1500)
      }
    } finally {
      wakeAbortController = null
      wakeListening.value = false
      wakeSessionInFlight.value = false
      await sleep(400)
    }
  }
  wakeLoopRunning = false
  wakeListening.value = false
  wakePauseReason.value = ''
}

const toggleWake = () => {
  wakeEnabled.value = !wakeEnabled.value
  localStorage.setItem('wake_enabled', wakeEnabled.value ? '1' : '0')
  if (wakeEnabled.value) {
    wakeLoop()
  } else {
    wakeListening.value = false
  }
}

onMounted(async () => {
  syncVoiceSessionBusy(null)
  clearStaleVoiceSessionOnIdleRoute()
  refreshVoiceSessionBusy()
  window.addEventListener(VOICE_BUSY_EVENT, refreshVoiceSessionBusy)
  tickClock()
  await refreshVoiceHealthWithRetry()
  clockTimer = window.setInterval(tickClock, 1000)
  statusTimer = window.setInterval(() => {
    refreshVoiceHealth()
  }, 4000)
  if (wakeEnabled.value) {
    wakeLoop()
  }
})

const shouldStopVoiceOnRouteLeave = (oldPath, newPath) => {
  if (!oldPath || oldPath === newPath) return false
  if (isPhotoHandoffPending()) return false
  return VOICE_PAGE_ROUTES.has(oldPath) || getVoiceSessionBusy()
}

watch(
  () => route.path,
  (path, oldPath) => {
    if (shouldStopVoiceOnRouteLeave(oldPath, path)) {
      if (WAKE_IDLE_ROUTES.has(path)) {
        releaseVoiceSession({ cancelWake: false })
      } else {
        emitVoiceStop()
      }
    }
    if (WAKE_IDLE_ROUTES.has(path)) {
      void armWakeOnIdleRoute()
    } else {
      void stopGlobalWakeListen()
      refreshVoiceSessionBusy()
      if (wakeEnabled.value) {
        wakeLoop()
      }
    }
  }
)

watch(voiceSessionBusyType, (busy) => {
  if (busy && !WAKE_IDLE_ROUTES.has(route.path)) {
    stopGlobalWakeListen()
  }
})

onUnmounted(() => {
  wakeEnabled.value = false
  if (armWakeTimer) {
    window.clearTimeout(armWakeTimer)
    armWakeTimer = null
  }
  window.removeEventListener(VOICE_BUSY_EVENT, refreshVoiceSessionBusy)
  window.clearInterval(clockTimer)
  window.clearInterval(statusTimer)
})
</script>
