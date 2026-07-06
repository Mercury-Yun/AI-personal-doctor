import { cancelWakeSession, getDeviceStatus, listenVoice, pauseWakeListening, startPhotoMode, stopActiveSpeech, stopVoiceMode } from '../api/device'

export const VOICE_STOP_EVENT = 'app-voice-stop'
export const VOICE_BUSY_EVENT = 'voice-session-busy-changed'

const SESSION_EXIT_RE = /^(退出|结束|再见|不问了|没有了|不用了|停止|算了|回去|退出连续)/

export function getVoiceSessionBusy() {
  return sessionStorage.getItem('voice_session_busy')
}

export function syncVoiceSessionBusy(type) {
  if (type) {
    sessionStorage.setItem('voice_session_busy', type)
  } else {
    sessionStorage.removeItem('voice_session_busy')
  }
  window.dispatchEvent(new CustomEvent(VOICE_BUSY_EVENT, { detail: { type: type || null } }))
}

export function voiceSessionStatusLabel(type) {
  if (type === 'doctor') return '问诊中'
  if (type === 'photo') return '问药中'
  return ''
}

export function isSessionExitPhrase(text) {
  return SESSION_EXIT_RE.test((text || '').trim())
}

/** 结束语音会话；唤醒由 WakeController 统一管理 */
export function releaseVoiceSession({ cancelWake = false, emitStop = false } = {}) {
  stopActiveSpeech().catch(() => {})
  if (cancelWake) {
    cancelWakeSession().catch(() => {})
  }
  syncVoiceSessionBusy(null)
  sessionStorage.removeItem('wake_chat_payload')
  if (emitStop) {
    window.dispatchEvent(new CustomEvent(VOICE_STOP_EVENT))
  }
}

/** 全局停止语音会话：中断 TTS、取消唤醒并清 busy（显式结束/打断时用） */
export function emitVoiceStop() {
  releaseVoiceSession({ cancelWake: true, emitStop: true })
}

/** 停止当前 TTS 并等待播完 */
export async function stopAllTts(maxMs = 15000) {
  await stopActiveSpeech().catch(() => {})
  await waitForTtsIdle(maxMs)
}

/** 拍照前：进入拍照模式（勿 cancelWake，会打断刚就绪的 demo） */
export async function prepareForPhotoCapture() {
  await preparePhotoModeForCapture()
}

function isCaptureReady(data) {
  if (!data) return false
  // 云端化后：online + photo_mode + !capture_active
  return Boolean(data.online && data.photo_mode && !data.capture_active)
}

/** 等待摄像头就绪（不再依赖 demo） */
export async function waitForDemoReady(maxMs = 30000, pollMs = 250) {
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    try {
      const { data } = await getDeviceStatus()
      if (isCaptureReady(data)) {
        await sleep(120)
        const { data: again } = await getDeviceStatus()
        if (isCaptureReady(again)) return true
      }
    } catch {
      /* retry */
    }
    await sleep(pollMs)
  }
  return false
}

/** 问诊/唤醒转问药前：停 TTS 并释放 demo 听写 */
export async function releaseDemoVoiceForPhoto() {
  await stopActiveSpeech().catch(() => {})
  await stopVoiceMode().catch(() => {})
  await waitForTtsIdle(1500)
}

/** 问药页内等待 demo 就绪（单一入口，避免重复 restart） */
let _photoPrepPromise = null

/** 进入问药/拍照：仅切换拍照模式（本地摄像头无需 demo 预热） */
export async function ensurePhotoReady({ voicePrepDone = false } = {}) {
  try {
    const { data } = await getDeviceStatus()
    if (isCaptureReady(data)) return true
  } catch {
    /* continue */
  }

  if (!voicePrepDone) {
    await stopActiveSpeech().catch(() => {})
    await waitForTtsIdle(1500)
  }

  try {
    const { data } = await getDeviceStatus()
    if (!data.photo_mode) {
      await startPhotoMode(180)
    }
  } catch {
    await startPhotoMode(180).catch(() => {})
  }

  await sleep(200)
  return true
}

/** 后台预热：仅发起请求，不重复调用 */
export function kickPhotoModePrep(seconds = 180) {
  if (_photoPrepPromise) return _photoPrepPromise
  _photoPrepPromise = (async () => {
    try {
      await releaseDemoVoiceForPhoto()
      await startPhotoMode(seconds)
      return await waitForDemoReady(40000, 250)
    } catch {
      return false
    } finally {
      _photoPrepPromise = null
    }
  })()
  return _photoPrepPromise
}

/** 会话内再次拍照：不重启 demo */
export async function ensureCaptureReady({ inSession = false } = {}) {
  try {
    const { data } = await getDeviceStatus()
    if (isCaptureReady(data)) return true
    if (inSession && data.photo_mode && data.online && !data.capture_active) {
      return true
    }
  } catch {
    /* fall through */
  }
  return ensurePhotoReady({ voicePrepDone: true })
}

/** 进入问药/拍照：切换拍照模式并等 demo 就绪（勿再 cancelWake） */
export async function preparePhotoModeForCapture() {
  await ensurePhotoReady({ voicePrepDone: false })
}

export async function quickPreparePhotoCapture({ voicePrepDone = false, inSession = false } = {}) {
  if (voicePrepDone || inSession) {
    await ensureCaptureReady({ inSession: true })
    return
  }
  await stopActiveSpeech().catch(() => {})
  await preparePhotoModeForCapture()
}

export async function waitForTtsIdle(maxMs = 30000, pollMs = 300) {
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    try {
      const { data } = await getDeviceStatus()
      if (!data.tts_busy) {
        await sleep(250)
        const { data: again } = await getDeviceStatus()
        if (!again.tts_busy) return true
      }
    } catch {
      await sleep(pollMs)
      continue
    }
    await sleep(pollMs)
  }
  return false
}

export async function waitForSpokenAnswerIdle(maxMs = 45000, pollMs = 300) {
  await waitForTtsIdle(maxMs)
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    try {
      const { data } = await getDeviceStatus()
      // 云端化后不再检查 demo_busy
      if (data.online && !data.capture_active && !data.tts_busy) {
        await sleep(300)
        const { data: again } = await getDeviceStatus()
        if (again.online && !again.capture_active && !again.tts_busy) {
          return true
        }
      }
    } catch {
      /* retry */
    }
    await sleep(pollMs)
  }
  return false
}

export async function listenWithRetry(prompt = false, speakFirst = '', attempts = 5) {
  let lastError = null
  for (let i = 0; i < attempts; i += 1) {
    try {
      const { data } = await listenVoice(prompt, speakFirst)
      const text = (data?.text || '').trim()
      if (text) {
        return { data: { text } }
      }
      if (i < attempts - 1) {
        await sleep(800 + i * 400)
        continue
      }
      return { data: { text: '' } }
    } catch (error) {
      lastError = error
      const status = error?.response?.status
      const detail = String(error?.response?.data?.detail || error?.message || '')
      const retryable = status === 400 || status === 503 || /重启|未就绪|离线|正忙|refused/i.test(detail)
      if (retryable && i < attempts - 1) {
        await sleep(1500 + i * 800)
        continue
      }
      throw error
    }
  }
  throw lastError
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}
