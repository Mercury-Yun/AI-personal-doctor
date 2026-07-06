import { getDeviceStatus, getWakeInfo, resetWakeSession, wakeSession } from '../api/device'
import { useWakeStore } from '../stores/wake'
import { useVoiceSessionStore } from '../stores/voiceSession'
import { resolveWakeRoute } from '../utils/wakeHandoff'
import { syncVoiceSessionBusy } from '../utils/voiceSession'

export const WAKE_IDLE_ROUTES = new Set([
  '/',
  '/dashboard',
  '/device',
  '/profiles',
  '/medications',
  '/reminders',
])

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const state = {
  loopGen: 0,
  running: false,
  abort: null,
  router: null,
  route: null,
  healthTimer: null,
  voiceOnline: null,
  offlineStreak: 0,
  wakeOfflineStreak: 0,
  captureActive: false,
  ttsBusy: false,
}

function store() {
  return useWakeStore()
}

function voiceStore() {
  return useVoiceSessionStore()
}

function currentPath() {
  return (state.route && state.route.path) || '/'
}

function isIdleRoute(path) {
  return WAKE_IDLE_ROUTES.has(path !== undefined ? path : currentPath())
}

function canListen() {
  const s = store()
  const voice = voiceStore()
  return (
    s.enabled &&
    isIdleRoute() &&
    s.available === true &&
    state.voiceOnline === true &&
    !voice.busyType &&
    !state.captureActive
  )
}

async function refreshVoiceStatus() {
  const s = store()
  const hold = s.sessionInFlight || s.listening || state.ttsBusy || Boolean(voiceStore().busyType)
  try {
    const { data } = await getDeviceStatus()
    state.ttsBusy = Boolean(data.tts_busy || data.tts_playing)
    state.captureActive = Boolean(data.capture_active)
    if (data.online) {
      state.voiceOnline = true
      state.offlineStreak = 0
      return true
    }
    if (hold && state.voiceOnline === true) return true
    state.offlineStreak += 1
    if (state.offlineStreak >= 8 || state.voiceOnline === null) {
      state.voiceOnline = false
    }
    return false
  } catch (err) {
    if (hold && state.voiceOnline === true) return true
    state.offlineStreak += 1
    if (state.offlineStreak >= 8 || state.voiceOnline === null) {
      state.voiceOnline = false
    }
    return false
  }
}

async function refreshWakeInfo() {
  const s = store()
  if (s.sessionInFlight) return s.available !== false
  try {
    const { data } = await getWakeInfo()
    s.setWord(data.wake_word || '小医')
    if (data.enabled && data.kws_enabled) {
      state.wakeOfflineStreak = 0
      s.setAvailable(true)
      s.setError(state.captureActive ? '正在拍照，请稍候…' : '')
      return true
    }
    s.setError(data.error || '唤醒未就绪')
    if (s.sessionInFlight && s.available === true) return true
    state.wakeOfflineStreak += 1
    if (state.wakeOfflineStreak >= 8 || s.available === null) {
      s.setAvailable(false)
    }
    return s.available === true
  } catch (err) {
    const detail = (err && err.response && err.response.data && err.response.data.detail)
      || (err && err.message)
      || '无法连接语音服务'
    s.setError(detail)
    if (s.sessionInFlight && s.available === true) return true
    state.wakeOfflineStreak += 1
    if (state.wakeOfflineStreak >= 8 || s.available === null) {
      s.setAvailable(false)
    }
    return false
  }
}

async function refreshHealth() {
  const s = store()
  if (s.sessionInFlight) {
    return s.available === true && state.voiceOnline === true
  }
  const results = await Promise.all([refreshVoiceStatus(), refreshWakeInfo()])
  return results[0] && results[1]
}

function startHealthPolling() {
  if (state.healthTimer) return
  state.healthTimer = window.setInterval(() => {
    refreshHealth()
    if (store().enabled && isIdleRoute() && !state.running) {
      ensureLoop()
    }
  }, 5000)
}

function stopHealthPolling() {
  if (state.healthTimer) {
    window.clearInterval(state.healthTimer)
    state.healthTimer = null
  }
}

async function stop(syncBackend) {
  state.loopGen += 1
  if (state.abort) {
    state.abort.abort()
    state.abort = null
  }
  store().setPhase('off')
  if (syncBackend) {
    await resetWakeSession().catch(() => {})
  }
}

async function handleWakeResult(payload) {
  const s = store()
  s.setPhase('handling')
  const target = await resolveWakeRoute(payload)
  s.setHandoff({ ...payload, routeTarget: target === 'photo' ? 'photo' : 'chat' })
  if (target === 'photo') {
    syncVoiceSessionBusy('photo')
    await state.router.push('/photo-medicine')
  } else {
    syncVoiceSessionBusy('doctor')
    await state.router.push('/doctor-chat')
  }
  s.setPhase('blocked')
}

async function runLoop(gen) {
  if (state.running) return
  state.running = true
  const s = store()

  while (gen === state.loopGen && s.enabled) {
    if (!isIdleRoute()) break

    if (!canListen()) {
      s.setPhase('blocked')
      if (!s.available) {
        s.setError(s.error || '唤醒未就绪')
      } else if (state.voiceOnline === false) {
        s.setError('语音离线，正在重连…')
      } else if (voiceStore().busyType) {
        s.setError('语音会话进行中')
      }
      await Promise.all([refreshHealth(), sleep(1200)])
      continue
    }

    s.setError('')
    s.setPhase('listening')
    state.abort = new AbortController()

    try {
      const { data } = await wakeSession({ signal: state.abort.signal })
      if (gen !== state.loopGen || !s.enabled || !isIdleRoute()) continue
      await handleWakeResult(data)
    } catch (err) {
      if (gen !== state.loopGen) break
      const status = err && err.response && err.response.status
      const code = err && err.code
      const name = err && err.name
      if (code === 'ERR_CANCELED' || name === 'CanceledError' || status === 499) {
        s.setPhase('off')
        await sleep(300)
        continue
      }
      if (status === 409 || status === 504) {
        s.setError('正在连接唤醒…')
        await sleep(2000)
        continue
      }
      s.setPhase('error')
      const detail = (err && err.response && err.response.data && err.response.data.detail)
        || '唤醒异常，稍后重试'
      s.setError(detail)
      await sleep(2000)
    } finally {
      state.abort = null
      if (gen === state.loopGen && s.phase === 'listening') {
        s.setPhase('off')
      }
    }
  }

  state.running = false
  if (gen === state.loopGen && s.phase === 'listening') {
    s.setPhase('off')
  }
}

function ensureLoop() {
  const s = store()
  if (!s.enabled || !isIdleRoute() || state.running) return
  state.loopGen += 1
  const gen = state.loopGen
  runLoop(gen)
}

function bind(router, route) {
  state.router = router
  state.route = route
}

function onRouteChange(path) {
  const s = store()
  if (isIdleRoute(path)) {
    if (s.enabled) ensureLoop()
    return
  }
  stop(false)
}

function onVoiceBusyChanged(busy) {
  const s = store()
  if (busy) {
    if (!isIdleRoute()) stop(false)
    s.setPhase('blocked')
    return
  }
  if (s.enabled && isIdleRoute() && s.phase === 'blocked') {
    s.setPhase('off')
    ensureLoop()
  }
}

async function boot() {
  const s = store()
  s.setPhase('booting')
  await refreshHealth()
  s.setPhase('off')
  if (s.enabled) ensureLoop()
  startHealthPolling()
}

function shutdown() {
  stopHealthPolling()
  stop(true)
}

function toggleEnabled() {
  const s = store()
  s.setEnabled(!s.enabled)
  if (s.enabled) {
    ensureLoop()
  } else {
    stop(true)
  }
}

function getVoiceOnline() {
  return state.voiceOnline
}

function getCaptureActive() {
  return state.captureActive
}

function getTtsBusy() {
  return state.ttsBusy
}

export const wakeController = {
  bind,
  boot,
  shutdown,
  stop,
  ensureLoop,
  refreshHealth,
  onRouteChange,
  onVoiceBusyChanged,
  toggleEnabled,
  isIdleRoute,
  getVoiceOnline,
  getCaptureActive,
  getTtsBusy,
}

export function useWakeController() {
  return wakeController
}
