import { classifyIntent } from '../api/device'

export const WAKE_CHAT_KEY = 'wake_chat_payload'
export const WAKE_PHOTO_KEY = 'wake_photo_payload'
export const PHOTO_HANDOFF_TS_KEY = 'photo_session_handoff'

const PHOTO_QUICK_RE =
  /拍照|问药|识药|什么药|这是什么|这是啥|那是啥|药盒|包装上|识别药|拍药|看看药|怎么吃|怎么用|用法|用量/

export function isHandoffPayload(payload) {
  return Boolean(payload?.fast_handoff || payload?.reminder_verify)
}

export function markPhotoHandoff() {
  sessionStorage.setItem(PHOTO_HANDOFF_TS_KEY, String(Date.now()))
}

export function buildWakeHandoff(payload, extra = {}) {
  return {
    ...payload,
    ...extra,
    fast_handoff: true,
  }
}

export function quickPhotoIntent(text) {
  const normalized = (text || '').trim()
  if (!normalized) return false
  return PHOTO_QUICK_RE.test(normalized)
}

/** 唤醒后决定去问诊还是问药（后端 intent 优先，前端再兜底分类） */
export async function resolveWakeRoute(payload) {
  const text = (payload?.text || '').trim()
  if (payload?.intent === 'photo') return 'photo'
  if (quickPhotoIntent(text)) return 'photo'
  if (!text) return 'doctor'
  try {
    const { data } = await classifyIntent(text)
    return data.intent === 'photo' ? 'photo' : 'doctor'
  } catch {
    return 'doctor'
  }
}

export function readWakePayload(key) {
  const raw = sessionStorage.getItem(key)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function clearWakePayload(key) {
  sessionStorage.removeItem(key)
}

/** 等全局唤醒 HTTP 结束，避免子页面误判「仍在听小医」 */
export async function waitForWakeSessionIdle(getInFlight, maxMs = 3500) {
  const deadline = Date.now() + maxMs
  while (getInFlight() && Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, 150))
  }
  return !getInFlight()
}
