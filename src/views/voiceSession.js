import { cancelWakeSession, getDeviceStatus, listenVoice, pauseWakeListening, resumeWakeListening, startPhotoMode, stopActiveSpeech } from '../api/device'

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

/** 结束语音会话；回首页时 cancelWake=false，避免刚恢复的「豆包」监听又被 cancel 掉 */
export function releaseVoiceSession({ cancelWake = false, emitStop = false } = {}) {
  stopActiveSpeech().catch(() => {})
  if (cancelWake) {
    cancelWakeSession().catch(() => {})
  }
  syncVoiceSessionBusy(null)
  sessionStorage.removeItem('wake_chat_payload')
  resumeWakeListening().catch(() => {})
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

/** 等待 demo 在线且未在拍照（拍照模式切换后调用） */
export async function waitForDemoReady(maxMs = 45000, pollMs = 600) {
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    try {
      const { data } = await getDeviceStatus()
      if (data.online && !data.capture_active) {
        await sleep(400)
        const { data: again } = await getDeviceStatus()
        if (again.online && !again.capture_active) return true
      }
    } catch {
      /* retry */
    }
    await sleep(pollMs)
  }
  return false
}

/** 进入问药/拍照：切换拍照模式并等 demo 就绪（勿再 cancelWake） */
export async function preparePhotoModeForCapture() {
  await startPhotoMode(180).catch(() => {})
  const ok = await waitForDemoReady(45000)
  if (!ok) {
    throw new Error('语音引擎准备超时，请稍后再试')
  }
}

/** @deprecated 用 preparePhotoModeForCapture */
export async function quickPreparePhotoCapture({ voicePrepDone = false } = {}) {
  if (voicePrepDone) return
  await stopActiveSpeech().catch(() => {})
  await preparePhotoModeForCapture()
}

export async function waitForTtsIdle(maxMs = 180000, pollMs = 400) {
  const start = Date.now()
  while (Date.now() - start < maxMs) {
    try {
      const { data } = await getDeviceStatus()
      if (!data.tts_busy) {
        await sleep(300)
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
