<template>
  <section class="compact-page photo-page">
    <div class="compact-page__head photo-page__head">
      <div class="head-left">
        <button type="button" class="back-btn" aria-label="返回首页" @click="goHome">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <h1>{{ isReminderVerifySession ? '用药确认' : '拍照识药' }}</h1>
      </div>
      <el-select v-model="selectedUserId" placeholder="选择患者" @change="handleUserChange">
        <el-option v-for="user in users" :key="user.id" :label="user.name" :value="user.id" />
      </el-select>
    </div>

    <div class="compact-page__body photo-shell">
      <aside class="capture-panel card">
        <div class="panel-title">
          <strong>{{ isReminderVerifySession ? '拍照核对' : '拍照识药' }}</strong>
          <span v-if="statusPill" class="status-pill">{{ statusPill }}</span>
        </div>
        <div class="preview-box">
          <img v-if="streamActive" :src="streamUrl" alt="摄像头实时画面" class="stream-live" />
          <img v-else-if="previewUrl" :src="previewUrl" alt="最近拍摄的药盒照片" />
          <div v-else class="preview-placeholder">
            <span class="preview-placeholder__icon">📷</span>
            <strong>药盒预览</strong>
            <p>{{ isReminderVerifySession ? '对准今天该吃的药盒' : '把药盒正面对准摄像头' }}</p>
          </div>
        </div>
        <p v-if="phaseHint" class="phase-hint">{{ phaseHint }}</p>
        <el-button
          class="capture-btn"
          type="primary"
          :loading="loading"
          :disabled="captureDisabled"
          @click="onPrimaryButton"
        >
          {{ captureLabel }}
        </el-button>
        <el-button v-if="photoSessionActive" class="stop-btn" link type="danger" @click="handleStopSession">
          结束
        </el-button>
      </aside>

      <main class="result-panel card">
        <div class="panel-title">
          <strong>识别结果</strong>
        </div>

        <div class="result-body">
          <div v-if="!medicineCard" class="result-empty">
            <div class="result-empty__icon">💊</div>
            <h2>{{ isReminderVerifySession ? '核对今天该吃的药' : '还没有识别结果' }}</h2>
            <p v-if="isReminderVerifySession">
              把提醒里的药盒对准摄像头，点左侧「{{ captureLabel }}」。核对正确后可点「继续问药」了解怎么吃。
            </p>
            <p v-else>
              点左侧「拍照识药」拍下药盒，我会识别药名，并在这里给出用法用量和注意事项。
            </p>
          </div>

          <div v-else-if="!medicineCard.name" class="result-empty result-empty--warn">
            <div class="result-empty__icon">🔍</div>
            <h2>没能看清药名</h2>
            <p>{{ medicineCard.note }}</p>
          </div>

          <div v-else class="med-card">
            <div v-if="verifyStatus" class="verify-banner" :class="verifyStatus">
              {{
                verifyStatus === 'ok'
                  ? '✓ 核对正确，可以按提醒服用'
                  : '✕ 这盒药和提醒不一致，请换正确的药盒重新拍照'
              }}
            </div>

            <div class="med-card__head">
              <div class="med-name">
                <strong>{{ medicineCard.name }}</strong>
                <span v-if="medicineCard.spec" class="med-spec">{{ medicineCard.spec }}</span>
              </div>
              <span v-if="medicineCard.category" class="med-chip">{{ medicineCard.category }}</span>
            </div>
            <p v-if="recognizedHint" class="recognized-hint">{{ recognizedHint }}</p>

            <section v-if="medicineCard.uses" class="med-section">
              <h3>治疗用途</h3>
              <p>{{ medicineCard.uses }}</p>
            </section>
            <section v-if="medicineCard.usage" class="med-section">
              <h3>用法用量</h3>
              <p>{{ medicineCard.usage }}</p>
            </section>
            <section v-if="medicineCard.cautions && medicineCard.cautions.length" class="med-section">
              <h3>注意事项</h3>
              <ol class="med-cautions">
                <li v-for="(item, idx) in medicineCard.cautions" :key="idx">{{ item }}</li>
              </ol>
            </section>

            <p v-if="medicineCard.note" class="med-note">{{ medicineCard.note }}</p>
            <p v-if="medicineCard.source" class="med-source">来源：{{ medicineCard.source }}</p>
          </div>
        </div>

        <div v-if="medicineCard && medicineCard.name" class="result-actions">
          <el-button type="primary" :disabled="loading" @click="handleContinueConsult()">继续问药</el-button>
          <el-button :disabled="loading" @click="handleRetake">换一个</el-button>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { identifyMedicine } from '../api/chat'
import {
  ackReminder,
  capturePhoto,
  getCameraPreviewUrl,
  getCameraStreamUrl,
  startCameraStream,
  stopCameraStream,
  pauseReminderTts,
  resumeReminderTts,
  speakText,
  stopPhotoMode,
} from '../api/device'
import { getUsers } from '../api/users'
import {
  buildWakeHandoff,
  clearWakePayload,
  isHandoffPayload,
  markPhotoHandoff,
  PHOTO_HANDOFF_TS_KEY,
  readWakePayload,
  waitForWakeSessionIdle,
  WAKE_CHAT_KEY,
  WAKE_PHOTO_KEY,
} from '../utils/wakeHandoff'
import { useWakeStore } from '../stores/wake'
import {
  ensureCaptureReady,
  ensurePhotoReady,
  getVoiceSessionBusy,
  isSessionExitPhrase,
  listenWithRetry,
  quickPreparePhotoCapture,
  releaseVoiceSession,
  stopAllTts,
  syncVoiceSessionBusy,
  VOICE_STOP_EVENT,
  waitForTtsIdle,
} from '../utils/voiceSession'

const PHOTO_HOLD_MS = 600
const PHOTO_HANDOFF_GUARD_MS = 180000
const CAPTURE_READY_SPEECH = '请对准药盒'
const CAPTURE_DONE_SPEECH = '拍好了'
const HANDOFF_CAPTURE_SPEECH = '请把药盒对准摄像头，两秒后拍照'
const RECAPTURE_READY_SPEECH = '请对准药盒'
const REMINDER_CAPTURE_SPEECH = '请拿今天该吃的药盒，对准摄像头，两秒后拍照'
const REMINDER_RETAKE_CAPTURE_SPEECH = '请拿正确的药盒对准摄像头，两秒后拍照'
const REMINDER_WRONG_BUTTON_SPEECH = '这盒好像不是这个时间该吃的药哦，请换正确的药盒，然后点下方重新拍照核对'
const REMINDER_WRONG_REPEAT_SPEECH = '还是不太对呢，麻烦您换正确的药盒，再点下方重新拍照核对'
const REMINDER_SESSION_TTS_PAUSE_SEC = 900
const SESSION_END_SPEECH = '好的，有需要随时叫我'
const SWITCH_TO_DOCTOR_SPEECH = '好的，我们来聊聊健康问题'
const SWITCH_TO_DOCTOR_LISTEN_SPEECH = '好的，您说说哪里不舒服'
const CARD_COMMAND_HINT = '要了解更多可以说继续问药，换药请说换一个，说退出返回首页'

const DOCTOR_SWITCH_ONLY_PHRASES = [
  '切换问诊',
  '去问医',
  '转到问诊',
  '换问诊',
  '改成问诊',
  '不想问药',
  '不问药',
  '别问药',
  '不问这个药',
  '问个别的问题',
  '问别的',
  '别的健康',
  '换个话题',
  '健康咨询',
  '一般问诊',
]

const RECAPTURE_PHRASES = [
  '换一个',
  '换一盒',
  '换个药',
  '换药',
  '换盒',
  '重拍',
  '重新拍',
  '再拍',
  '换一种',
  '下一个',
  '换下一个',
  '换个',
]

const router = useRouter()
const wakeSessionInFlight = inject('wakeSessionInFlight', ref(false))

const goHome = () => router.push('/dashboard')

const users = ref([])
const selectedUserId = ref(null)
const loading = ref(false)
const phase = ref('idle')
const previewUrl = ref('')
const previewMeta = ref('')
const streamActive = ref(false)
const streamUrl = ref('')
const photoSessionActive = ref(false)
const hasCapturedPhoto = ref(false)
const medicineCard = ref(null)
const verifyStatus = ref(null)
const reminderVerifyContext = ref(null)
const reminderNeedsRecapture = ref(false)
const reminderWrongNotified = ref(false)
let sessionEpoch = 0
let turnLock = false
let identifyAbortController = null
let captureAbortController = null
let routeLeaveHandled = false
let remindersQuieted = false

const isReminderVerifySession = computed(() => Boolean(reminderVerifyContext.value))

const statusPill = computed(() => {
  if (loading.value) {
    if (phase.value === 'preparing') return '准备中'
    if (phase.value === 'speaking') return '播报中'
    if (phase.value === 'capturing') return '拍照中'
    if (phase.value === 'identifying') return '识别中'
    if (phase.value === 'listening') return '聆听中'
  }
  if (reminderNeedsRecapture.value && isReminderVerifySession.value) return '请换盒重拍'
  return ''
})

const phaseHint = computed(() => {
  if (phase.value === 'preparing') return '正在准备摄像头，请稍候…'
  if (phase.value === 'speaking') return '正在播报，请把药盒对准摄像头…'
  if (phase.value === 'capturing') return '正在对焦拍照，请拿稳药盒…'
  if (phase.value === 'identifying') return '正在识别药品，请稍候…'
  if (phase.value === 'listening') return '请说：继续问药 / 换一个 / 退出'
  if (reminderNeedsRecapture.value && isReminderVerifySession.value) return '请换正确的药盒，再点下方按钮'
  return ''
})

const recognizedHint = computed(() => {
  const card = medicineCard.value
  if (!card || !card.recognized_name) return ''
  if (card.matched && card.recognized_name !== card.name) {
    return `识别到：${card.recognized_name}`
  }
  return ''
})

const captureLabel = computed(() => {
  if (wakeSessionInFlight.value && !photoSessionActive.value) return '唤醒占用中...'
  if (loading.value) {
    if (phase.value === 'preparing') return '准备中...'
    if (phase.value === 'speaking') return '请听提示...'
    if (phase.value === 'capturing') return '拍照中...'
    if (phase.value === 'identifying') return '识别中...'
    if (phase.value === 'listening') return '请说话...'
    return '处理中...'
  }
  if (photoSessionActive.value && reminderNeedsRecapture.value && isReminderVerifySession.value) {
    return '重新拍照核对'
  }
  if (photoSessionActive.value) return '识别进行中...'
  if (isReminderVerifySession.value) return '拍照核对'
  return medicineCard.value ? '重新拍照' : '拍照识药'
})

const captureDisabled = computed(() => {
  if (loading.value) return true
  if (wakeSessionInFlight.value && !photoSessionActive.value) return true
  if (photoSessionActive.value && !(reminderNeedsRecapture.value && isReminderVerifySession.value)) {
    return true
  }
  return false
})

const formatError = (error) => {
  const detail = error?.response?.data?.detail || error?.message
  if (typeof detail === 'string' && detail.trim()) {
    if (/timeout|time exceeded|timed out/i.test(detail)) {
      return '处理超时，请稍等几秒后点「换一个」或返回首页再试'
    }
    return detail
  }
  if (error?.code === 'ECONNABORTED') return '处理超时，请稍等几秒后重试'
  return '拍照识药失败，请再试一次'
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const isLiveSession = (epoch) => epoch === sessionEpoch && photoSessionActive.value

const abortInflightRequests = () => {
  if (identifyAbortController) {
    identifyAbortController.abort()
    identifyAbortController = null
  }
  if (captureAbortController) {
    captureAbortController.abort()
    captureAbortController = null
  }
}

const syncVoiceBusyFlag = (active) => {
  if (active) {
    syncVoiceSessionBusy('photo')
  } else if (getVoiceSessionBusy() === 'photo') {
    syncVoiceSessionBusy(null)
  }
}

const refreshPhotoHandoff = () => {
  markPhotoHandoff()
}

const isPhotoHandoffActive = () => {
  const handoff = sessionStorage.getItem(PHOTO_HANDOFF_TS_KEY)
  return handoff && Date.now() - Number(handoff) < PHOTO_HANDOFF_GUARD_MS
}

const isPhotoCapturePhase = () =>
  photoSessionActive.value &&
  (loading.value || phase.value === 'capturing' || phase.value === 'speaking')

const shouldStopPhotoOnLeave = () =>
  photoSessionActive.value || loading.value || phase.value !== 'idle'

const finalizePhotoRouteLeave = () => {
  if (routeLeaveHandled) return
  routeLeaveHandled = true
  clearWakePayload(WAKE_PHOTO_KEY)
  clearWakePayload(PHOTO_HANDOFF_TS_KEY)
  if (shouldStopPhotoOnLeave()) {
    teardownPhotoSession({ markInterrupted: true })
  } else {
    void stopPhotoMode().catch(() => {})
    syncVoiceSessionBusy(null)
  }
  releaseVoiceSession({ cancelWake: false })
}

const teardownPhotoSession = ({ markInterrupted = false } = {}) => {
  sessionEpoch += 1
  abortInflightRequests()
  photoSessionActive.value = false
  turnLock = false
  loading.value = false
  phase.value = 'idle'
  syncVoiceBusyFlag(false)
  reminderVerifyContext.value = null
  reminderNeedsRecapture.value = false
  reminderWrongNotified.value = false
  if (remindersQuieted) {
    remindersQuieted = false
    void resumeReminderTts().catch(() => {})
  }
  void stopAllTts(10000).catch(() => {})
  void stopPhotoMode().catch(() => {})
  clearWakePayload(WAKE_PHOTO_KEY)
  clearWakePayload(PHOTO_HANDOFF_TS_KEY)
  if (markInterrupted) {
    sessionStorage.setItem('photo_session_interrupted', String(Date.now()))
  }
}

const onGlobalVoiceStop = () => {
  if (isPhotoHandoffActive() || isPhotoCapturePhase()) {
    return
  }
  if (phase.value === 'listening' && photoSessionActive.value) {
    return
  }
  if (photoSessionActive.value || loading.value) {
    teardownPhotoSession()
  }
}

// ---- 摄像头实时流管理 ----
const openCameraStream = async () => {
  try {
    await startCameraStream()
    streamUrl.value = getCameraStreamUrl()
    streamActive.value = true
  } catch (e) {
    console.warn('摄像头流启动失败:', e)
  }
}

const closeCameraStream = async () => {
  streamActive.value = false
  streamUrl.value = ''
  try {
    await stopCameraStream()
  } catch (e) {
    // 忽略
  }
}

// 恢复实时画面：拍照倒计时/重拍时都应显示摄像头画面
const resumeCameraStream = () => {
  if (streamUrl.value) {
    streamActive.value = true
  } else {
    openCameraStream()
  }
}

const resetPageState = () => {
  teardownPhotoSession()
  hasCapturedPhoto.value = false
  previewUrl.value = ''
  previewMeta.value = ''
  medicineCard.value = null
  verifyStatus.value = null
}

const withTurnLock = async (fn) => {
  if (turnLock) return { kind: 'busy' }
  turnLock = true
  try {
    return await fn()
  } finally {
    turnLock = false
  }
}

const keepReminderSessionQuiet = () => {
  if (isReminderVerifySession.value || reminderVerifyContext.value) {
    remindersQuieted = true
    void pauseReminderTts(REMINDER_SESSION_TTS_PAUSE_SEC).catch(() => {})
  }
}

const normalizeMedicineCore = (name) => {
  let text = (name || '').trim()
  for (const suffix of ['缓释片', '软胶囊', '胶囊', '颗粒', '注射液', '片']) {
    if (text.endsWith(suffix) && text.length > suffix.length) {
      text = text.slice(0, -suffix.length)
      break
    }
  }
  return text.trim()
}

const medicineNameMatches = (text, expectedName) => {
  const expected = (expectedName || '').trim()
  if (!expected) return false
  const normalized = (text || '').trim()
  if (!normalized) return false
  if (normalized.includes(expected) || expected.includes(normalized)) return true
  const core = normalizeMedicineCore(expected)
  const textCore = normalizeMedicineCore(normalized)
  return core.length >= 2 && (normalized.includes(core) || textCore.includes(core))
}

const isRecapturePhrase = (text) => {
  const t = (text || '').trim().replace(/[。！？.!?，,、\s]/g, '')
  if (!t) return false
  return RECAPTURE_PHRASES.some((phrase) => t.includes(phrase))
}

const isDoctorSwitchOnlyPhrase = (text) => {
  const normalized = (text || '').trim().replace(/[。！？.!?]+$/g, '')
  if (!normalized) return true
  if (DOCTOR_SWITCH_ONLY_PHRASES.includes(normalized)) return true
  if (normalized.includes('问诊') && !normalized.includes('问药') && normalized.length <= 10) {
    return /^(去|转|切换|改成|开始|进入)/.test(normalized) || normalized === '问诊'
  }
  return false
}

const switchToDoctorChat = async (text) => {
  abortInflightRequests()
  const questionText = (text || '').trim()
  const switchOnly = isDoctorSwitchOnlyPhrase(questionText)
  const payload = {
    user_id: selectedUserId.value,
    intent: 'chat',
    text: switchOnly ? '' : questionText,
    needs_listen: switchOnly,
  }
  try {
    await speakText(switchOnly ? SWITCH_TO_DOCTOR_LISTEN_SPEECH : SWITCH_TO_DOCTOR_SPEECH, true)
    await waitForTtsIdle()
  } catch {
    /* TTS optional */
  }
  teardownPhotoSession()
  sessionStorage.setItem(
    WAKE_CHAT_KEY,
    JSON.stringify(
      buildWakeHandoff({
        ...payload,
      }),
    ),
  )
  await router.push('/doctor-chat')
}

const exitPhotoSession = async ({ speech = SESSION_END_SPEECH, message = '已结束', goHome: navHome = true } = {}) => {
  teardownPhotoSession()
  releaseVoiceSession({ cancelWake: false })
  if (speech) {
    try {
      await speakText(speech, true)
    } catch {
      /* ignore TTS errors on exit */
    }
  }
  if (message) {
    ElMessage.success(message)
  }
  if (navHome) {
    await router.push('/dashboard')
  }
}

const handleStopSession = async () => {
  if (!photoSessionActive.value && !loading.value) return
  await exitPhotoSession()
}

const notifyReminderWrong = async (epoch = sessionEpoch) => {
  reminderNeedsRecapture.value = true
  keepReminderSessionQuiet()
  ElMessage.warning('药盒不对，请换正确的药盒后点击下方「重新拍照核对」')
  if (!isLiveSession(epoch)) return
  const hint = reminderWrongNotified.value
    ? REMINDER_WRONG_REPEAT_SPEECH
    : REMINDER_WRONG_BUTTON_SPEECH
  reminderWrongNotified.value = true
  try {
    await speakText(hint, true)
    await waitForTtsIdle(12000)
  } catch {
    /* optional */
  }
}

const capturePhotoWithTimeout = async (ms = 55000, epoch = sessionEpoch) => {
  const timeoutMs = Math.max(ms, 45000)
  captureAbortController = new AbortController()
  const timer = window.setTimeout(() => captureAbortController.abort(), timeoutMs)
  try {
    const result = await capturePhoto({ signal: captureAbortController.signal })
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }
    return result
  } finally {
    window.clearTimeout(timer)
    captureAbortController = null
  }
}

const capturePhotoOnly = async ({
  skipDoneSpeech = false,
  compact = false,
  handoff = false,
  fastHandoff = false,
  reminderVerify = false,
  retake = false,
  recapture = false,
  compactRecapture = false,
  voicePrepDone = false,
  inSession = false,
  epoch = sessionEpoch,
} = {}) => {
  await ensureCaptureReady({
    inSession: inSession || voicePrepDone || handoff || recapture || compactRecapture,
  })
  if (handoff || reminderVerify || isReminderVerifySession.value) {
    keepReminderSessionQuiet()
  }
  refreshPhotoHandoff()

  // 拍照倒计时期间显示摄像头实时画面（含唤醒「两秒后拍照」路径）
  resumeCameraStream()

  let spokeCapturePrompt = false
  if (recapture) {
    phase.value = 'speaking'
    try {
      await speakText(RECAPTURE_READY_SPEECH, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else if (reminderVerify) {
    phase.value = 'speaking'
    try {
      await speakText(retake ? REMINDER_RETAKE_CAPTURE_SPEECH : REMINDER_CAPTURE_SPEECH, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else if (fastHandoff) {
    phase.value = 'speaking'
    try {
      await speakText(HANDOFF_CAPTURE_SPEECH, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else if (!handoff) {
    const prompt = compact ? '请对准药盒' : CAPTURE_READY_SPEECH
    phase.value = 'capturing'
    try {
      speakText(prompt, false).catch(() => {})
      spokeCapturePrompt = true
    } catch {
      /* optional */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else {
    phase.value = 'speaking'
    try {
      await speakText(HANDOFF_CAPTURE_SPEECH, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  }
  phase.value = 'capturing'
  try {
    if (spokeCapturePrompt) {
      await sleep(PHOTO_HOLD_MS)
    } else if (fastHandoff) {
      await sleep(200)
    } else if (handoff || compactRecapture) {
      await sleep(300)
    } else {
      await sleep(PHOTO_HOLD_MS)
    }
    refreshPhotoHandoff()
    if (!isLiveSession(epoch)) {
      const err = new Error('识药已取消')
      err.name = 'SessionAbort'
      throw err
    }

    let lastError = null
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      try {
        refreshPhotoHandoff()
        const { data } = await capturePhotoWithTimeout(55000, epoch)
        // 拍照成功后暂停实时流，显示拍摄的静态图
        streamActive.value = false
        previewUrl.value = getCameraPreviewUrl()
        previewMeta.value = data.width && data.height ? `${data.width} × ${data.height}` : '已拍照'
        hasCapturedPhoto.value = true
        phase.value = 'idle'
        lastError = null
        break
      } catch (error) {
        lastError = error
        if (!isLiveSession(epoch)) {
          throw error
        }
        const busy =
          error?.response?.status === 503 ||
          /正忙|busy/i.test(String(error?.response?.data?.detail || error?.message || ''))
        const cameraFail = /摄像头|camera|超时|暂不可用/i.test(
          String(error?.response?.data?.detail || error?.message || ''),
        )
        if (attempt < 2 && (busy || cameraFail)) {
          ElMessage.warning(
            cameraFail ? '摄像头恢复中，5 秒后重试…' : '语音引擎准备中，3 秒后重试拍照…',
          )
          await ensurePhotoReady({ voicePrepDone: true })
          await sleep(cameraFail ? 3000 : 2000)
          continue
        }
        if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError' || error?.name === 'AbortError') {
          throw new Error('拍照超时，请点「换一个」或返回首页再试')
        }
        throw error
      }
    }
    if (lastError) {
      throw lastError
    }

    if (!skipDoneSpeech) {
      speakText(CAPTURE_DONE_SPEECH, false).catch(() => {})
      await sleep(400)
    }
  } finally {
    if (phase.value === 'capturing' && isLiveSession(epoch)) {
      phase.value = 'idle'
    }
  }
}

const speakThenListen = async (prompt = '', epoch = sessionEpoch) => {
  if (prompt) {
    phase.value = 'speaking'
    try {
      await speakText(prompt, true)
      await waitForTtsIdle(20000)
      await sleep(350)
    } catch {
      /* 提示语失败不阻断听写 */
    }
    if (!isLiveSession(epoch)) {
      return { kind: 'abort' }
    }
  }

  phase.value = 'listening'
  try {
    const { data } = await listenWithRetry(false, '')
    if (!isLiveSession(epoch)) {
      return { kind: 'abort' }
    }
    const heard = (data.text || '').trim()
    if (!heard) {
      return { kind: 'empty' }
    }
    if (isSessionExitPhrase(heard)) {
      return { kind: 'exit' }
    }
    return { kind: 'ok', text: heard }
  } finally {
    if (isLiveSession(epoch) && phase.value === 'listening') {
      phase.value = 'idle'
    }
  }
}

const runIdentifyRequest = async (epoch) => {
  phase.value = 'identifying'
  abortInflightRequests()
  identifyAbortController = new AbortController()
  try {
    const { data } = await identifyMedicine(
      { user_id: selectedUserId.value || null },
      { signal: identifyAbortController.signal },
    )
    if (!isLiveSession(epoch)) return null
    return data
  } finally {
    identifyAbortController = null
  }
}

const buildCardSummarySpeech = (data, reminderConfirmed) => {
  if (!data?.name) {
    return data?.note || '没能看清药名，请把药盒正面对准摄像头重新拍照。'
  }
  const parts = []
  if (reminderConfirmed) parts.push('核对正确，是今天该吃的药。')
  const specText = data.spec ? `，规格${data.spec}` : ''
  parts.push(`识别到${data.name}${specText}。`)
  if (data.uses) parts.push(data.uses)
  if (!data.matched && data.note) parts.push(data.note)
  parts.push(CARD_COMMAND_HINT)
  return parts.join('')
}

const speakCardSummary = async (data, epoch, { reminderConfirmed = false } = {}) => {
  const speech = buildCardSummarySpeech(data, reminderConfirmed)
  if (!speech) return
  phase.value = 'speaking'
  try {
    await speakText(speech, true)
    await waitForTtsIdle(30000)
    await sleep(300)
  } catch {
    /* TTS optional */
  }
}

const listenForCardCommand = async (epoch) => {
  let attempts = 0
  while (attempts < 2) {
    if (!isLiveSession(epoch)) return { action: 'abort' }
    const listened = await speakThenListen(attempts === 0 ? '' : CARD_COMMAND_HINT, epoch)
    if (!isLiveSession(epoch)) return { action: 'abort' }
    if (listened.kind === 'abort') return { action: 'abort' }
    if (listened.kind === 'exit') return { action: 'exit' }
    if (listened.kind === 'empty') {
      attempts += 1
      continue
    }
    const text = listened.text || ''
    if (isRecapturePhrase(text)) return { action: 'recapture' }
    return { action: 'doctor', text }
  }
  return { action: 'done' }
}

const runIdentifyCore = async (
  epoch,
  { preset = '', fastHandoff = false, voicePrepDone = false, fromHandoff = false, retake = false } = {},
) => {
  let firstPass = true
  const presetText = (preset || '').trim()

  while (true) {
    if (!isLiveSession(epoch)) return { kind: 'abort' }
    const reminderMode = isReminderVerifySession.value

    if (!firstPass) {
      medicineCard.value = null
      verifyStatus.value = null
    }

    const captureOpts = { skipDoneSpeech: true, voicePrepDone, epoch }
    if (reminderMode) {
      captureOpts.reminderVerify = true
      captureOpts.retake = retake || !firstPass
      captureOpts.inSession = !firstPass
    } else if (firstPass && (fromHandoff || fastHandoff)) {
      captureOpts.handoff = true
      captureOpts.fastHandoff = fastHandoff
      captureOpts.compact = true
    } else if (firstPass) {
      captureOpts.compact = false
    } else {
      captureOpts.recapture = true
      captureOpts.compactRecapture = true
      captureOpts.handoff = true
      captureOpts.inSession = true
    }

    await capturePhotoOnly(captureOpts)
    if (!isLiveSession(epoch)) return { kind: 'abort' }

    const data = await runIdentifyRequest(epoch)
    if (!isLiveSession(epoch)) return { kind: 'abort' }
    if (!data) return { kind: 'abort' }
    medicineCard.value = data
    hasCapturedPhoto.value = true

    if (reminderMode) {
      const expected = reminderVerifyContext.value?.name || ''
      const recognized = data.recognized_name || data.name || ''
      const isMatch = Boolean(recognized) && medicineNameMatches(recognized, expected)
      if (!isMatch) {
        verifyStatus.value = 'wrong'
        await notifyReminderWrong(epoch)
        return { kind: 'verify_wrong' }
      }
      verifyStatus.value = 'ok'
      reminderNeedsRecapture.value = false
      reminderWrongNotified.value = false
      const ctx = reminderVerifyContext.value
      if (ctx?.medication_id) {
        try {
          await ackReminder(ctx.medication_id, ctx.take_time)
        } catch {
          /* backend may have already acked */
        }
      }
      ElMessage.success(`已确认服用：${ctx?.name || recognized}`)
      reminderVerifyContext.value = null
    }

    await speakCardSummary(data, epoch, { reminderConfirmed: reminderMode })
    if (!isLiveSession(epoch)) return { kind: 'abort' }

    let command
    if (firstPass && presetText && isSessionExitPhrase(presetText)) {
      command = { action: 'exit' }
    } else {
      command = await listenForCardCommand(epoch)
    }
    if (!isLiveSession(epoch)) return { kind: 'abort' }

    if (command.action === 'abort') return { kind: 'abort' }
    if (command.action === 'recapture') {
      firstPass = false
      continue
    }
    if (command.action === 'doctor') {
      await handleContinueConsult(command.text || '')
      return { kind: 'doctor' }
    }
    if (command.action === 'exit') return { kind: 'exit' }
    return { kind: 'done' }
  }
}

const runIdentifyTurn = async (epoch, options = {}) => withTurnLock(() => runIdentifyCore(epoch, options))

const handleIdentifyResult = async (result, epoch) => {
  if (result?.kind === 'busy') {
    if (isLiveSession(epoch)) teardownPhotoSession()
    ElMessage.info('识药正忙，请稍后再试')
    return
  }
  if (result?.kind === 'exit') {
    await exitPhotoSession()
    return
  }
  if (result?.kind === 'doctor') return
  if (result?.kind === 'abort') {
    if (isLiveSession(epoch)) teardownPhotoSession()
    return
  }
  if (result?.kind === 'verify_wrong') {
    if (isLiveSession(epoch)) {
      loading.value = false
      phase.value = 'idle'
    }
    return
  }
  teardownPhotoSession()
}

const beginIdentify = async () => {
  if (loading.value) return
  if (wakeSessionInFlight.value && !photoSessionActive.value) {
    ElMessage.info('正在等待唤醒词，请稍等几秒或回首页再试')
    return
  }
  if (photoSessionActive.value) return

  const epoch = sessionEpoch
  refreshPhotoHandoff()
  medicineCard.value = null
  verifyStatus.value = null
  // 重新拍照：恢复实时流画面
  resumeCameraStream()
  photoSessionActive.value = true
  syncVoiceBusyFlag(true)
  loading.value = true
  phase.value = 'preparing'
  try {
    await pauseReminderTts(45).catch(() => {})
    await quickPreparePhotoCapture()
    const result = await runIdentifyTurn(epoch, {})
    await handleIdentifyResult(result, epoch)
  } catch (error) {
    teardownPhotoSession({ markInterrupted: true })
    ElMessage.error(formatError(error))
  } finally {
    if (isLiveSession(epoch)) {
      loading.value = false
      phase.value = 'idle'
    }
  }
}

const reminderRecapture = async () => {
  if (loading.value || !photoSessionActive.value) return
  const epoch = sessionEpoch
  reminderNeedsRecapture.value = false
  verifyStatus.value = null
  medicineCard.value = null
  // 重新核对：恢复实时流画面
  resumeCameraStream()
  loading.value = true
  try {
    const result = await runIdentifyTurn(epoch, { retake: true })
    await handleIdentifyResult(result, epoch)
  } catch (error) {
    teardownPhotoSession({ markInterrupted: true })
    ElMessage.error(formatError(error))
  } finally {
    if (isLiveSession(epoch)) {
      loading.value = false
      phase.value = 'idle'
    }
  }
}

const onPrimaryButton = () => {
  if (loading.value) return
  if (photoSessionActive.value && reminderNeedsRecapture.value && isReminderVerifySession.value) {
    return reminderRecapture()
  }
  if (photoSessionActive.value) return
  return beginIdentify()
}

const handleRetake = () => onPrimaryButton()

const handleContinueConsult = async (text = '') => {
  const name = medicineCard.value?.name || ''
  const questionText = (text || '').trim() || (name ? `我想咨询一下${name}` : '')
  await switchToDoctorChat(questionText)
}

const loadUsers = async () => {
  const { data } = await getUsers()
  users.value = data
  if (data.length && !selectedUserId.value) {
    selectedUserId.value = data[0].id
  }
}

const handleUserChange = () => {
  teardownPhotoSession()
  medicineCard.value = null
  verifyStatus.value = null
  hasCapturedPhoto.value = false
  previewUrl.value = ''
  previewMeta.value = ''
}

let wakePayloadHandling = false

const handleWakePayload = async (payloadFromEvent = null) => {
  if (wakePayloadHandling) return

  let payload = payloadFromEvent
  if (!payload) {
    const wakeStore = useWakeStore()
    if (wakeStore.handoff && wakeStore.handoff.routeTarget === 'photo') {
      payload = wakeStore.handoff
      wakeStore.clearHandoff()
    } else {
      payload = readWakePayload(WAKE_PHOTO_KEY)
      if (!payload) return
    }
  }

  if (wakeSessionInFlight.value) {
    const ready = await waitForWakeSessionIdle(
      () => wakeSessionInFlight.value,
      isHandoffPayload(payload) ? 800 : 4000,
    )
    if (!ready && !isHandoffPayload(payload)) {
      ElMessage.info('正在等待唤醒词，请稍后再试')
      return
    }
  }

  wakePayloadHandling = true
  let handoffConsumed = false
  try {
    phase.value = 'preparing'
    loading.value = true
    photoSessionActive.value = true
    syncVoiceBusyFlag(true)
    try {
      await ensurePhotoReady({ voicePrepDone: Boolean(payload.voice_prep_done) })
    } catch (error) {
      teardownPhotoSession()
      ElMessage.error(error?.message || '语音引擎准备超时，请稍后再试')
      return
    }
    refreshPhotoHandoff()
    const preset = (payload.text || '').trim()
    if (payload.user_id) {
      selectedUserId.value = payload.user_id
    }
    reminderVerifyContext.value = payload.reminder_verify || null
    reminderNeedsRecapture.value = false
    reminderWrongNotified.value = false
    keepReminderSessionQuiet()

    const epoch = sessionEpoch
    loading.value = true

    try {
      const result = await runIdentifyTurn(epoch, {
        preset,
        fromHandoff: true,
        fastHandoff: Boolean(payload.fast_handoff),
        voicePrepDone: Boolean(payload.voice_prep_done),
      })
      if (!isLiveSession(epoch)) return
      if (result?.kind === 'busy') {
        sessionStorage.setItem(WAKE_PHOTO_KEY, JSON.stringify(payload))
        teardownPhotoSession()
        ElMessage.info('识药正忙，请稍后再试')
        return
      }
      if (result?.kind === 'exit') {
        clearWakePayload(WAKE_PHOTO_KEY)
        clearWakePayload(PHOTO_HANDOFF_TS_KEY)
        await exitPhotoSession({ speech: '好的，已取消', message: '已取消' })
        return
      }
      if (result?.kind === 'abort') {
        sessionStorage.setItem(WAKE_PHOTO_KEY, JSON.stringify(payload))
        teardownPhotoSession()
        ElMessage.warning('拍照未成功，请再点一次「拍照识药」')
        return
      }
      handoffConsumed = true
      clearWakePayload(WAKE_PHOTO_KEY)
      clearWakePayload(PHOTO_HANDOFF_TS_KEY)
      if (result?.kind === 'doctor') {
        return
      }
      if (result?.kind === 'verify_wrong') {
        return
      }
      teardownPhotoSession()
    } finally {
      if (isLiveSession(epoch)) {
        loading.value = false
        phase.value = 'idle'
      }
    }
  } catch (error) {
    sessionStorage.setItem(WAKE_PHOTO_KEY, JSON.stringify(payload))
    clearWakePayload(PHOTO_HANDOFF_TS_KEY)
    teardownPhotoSession({ markInterrupted: true })
    ElMessage.error(formatError(error))
  } finally {
    if (handoffConsumed) {
      clearWakePayload(WAKE_PHOTO_KEY)
    }
    wakePayloadHandling = false
  }
}

const onWakePhotoEvent = (event) => {
  handleWakePayload(event.detail)
}

const warnIfInterruptedSession = () => {
  const raw = sessionStorage.getItem('photo_session_interrupted')
  if (!raw) return
  sessionStorage.removeItem('photo_session_interrupted')
  ElMessage.info('已离开识药页面。若按钮无反应，请等约 10 秒或点「结束」后再试')
}

watch([photoSessionActive, loading], ([active, busy]) => {
  syncVoiceBusyFlag(active || busy)
})

onMounted(async () => {
  window.addEventListener('app-wake-photo', onWakePhotoEvent)
  window.addEventListener(VOICE_STOP_EVENT, onGlobalVoiceStop)
  // 进入页面即启动摄像头实时流
  openCameraStream()
  const wakeStore = useWakeStore()
  const storeHandoff =
    wakeStore.handoff && wakeStore.handoff.routeTarget === 'photo' ? wakeStore.handoff : null
  const pendingPayload = storeHandoff || readWakePayload(WAKE_PHOTO_KEY)
  if (pendingPayload) {
    hasCapturedPhoto.value = false
    previewUrl.value = ''
    previewMeta.value = ''
    medicineCard.value = null
    verifyStatus.value = null
  } else {
    resetPageState()
  }
  if (getVoiceSessionBusy() === 'photo' && !pendingPayload) {
    syncVoiceSessionBusy(null)
  }
  warnIfInterruptedSession()
  if (pendingPayload?.user_id) {
    selectedUserId.value = pendingPayload.user_id
  }
  const usersTask = loadUsers()
  const handoffTask = pendingPayload ? handleWakePayload() : null
  await usersTask
  if (pendingPayload?.user_id) {
    selectedUserId.value = pendingPayload.user_id
  }
  if (handoffTask) {
    await handoffTask
  }
})

onBeforeRouteLeave(() => {
  finalizePhotoRouteLeave()
  return true
})

onUnmounted(() => {
  window.removeEventListener('app-wake-photo', onWakePhotoEvent)
  window.removeEventListener(VOICE_STOP_EVENT, onGlobalVoiceStop)
  // 离开页面时关闭摄像头流
  closeCameraStream()
  if (!routeLeaveHandled) {
    finalizePhotoRouteLeave()
  }
  releaseVoiceSession({ cancelWake: false })
  sessionStorage.removeItem(WAKE_PHOTO_KEY)
  sessionStorage.removeItem(PHOTO_HANDOFF_TS_KEY)
})
</script>

<style scoped>
.photo-page {
  height: 100%;
  min-height: 0;
}

.photo-page__head {
  margin-bottom: 8px;
}

.photo-page__head h1 {
  font-size: 24px;
}

.photo-page__head .el-select {
  width: 150px;
}

.photo-shell {
  display: grid;
  grid-template-columns: minmax(0, 340px) minmax(0, 1fr);
  gap: 12px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.capture-panel,
.result-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  overflow: hidden;
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.panel-title strong {
  font-size: 19px;
}

.status-pill {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
}

.preview-box {
  width: 100%;
  aspect-ratio: 4 / 3;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 14px;
  background: #eef4fb;
  border: 1px solid var(--border);
}

.preview-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.preview-box .stream-live {
  animation: stream-live-pulse 2s ease-in-out infinite;
}

@keyframes stream-live-pulse {
  0%,
  100% {
    box-shadow: inset 0 0 0 2px rgba(64, 158, 255, 0.35);
  }
  50% {
    box-shadow: inset 0 0 0 2px rgba(64, 158, 255, 0.75);
  }
}

.preview-placeholder {
  text-align: center;
  color: var(--muted);
  padding: 12px;
}

.preview-placeholder__icon {
  font-size: 40px;
}

.preview-placeholder strong {
  display: block;
  font-size: 20px;
  margin: 8px 0 4px;
  color: var(--text);
}

.preview-placeholder p {
  margin: 0;
  font-size: 15px;
}

.phase-hint {
  margin: 0;
  text-align: center;
  color: var(--muted);
  font-size: 15px;
  min-height: 20px;
}

.capture-btn {
  width: 100%;
  min-height: 60px;
  font-size: 22px;
  font-weight: 700;
}

.stop-btn {
  align-self: center;
}

.result-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.result-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--muted);
  gap: 6px;
  padding: 16px;
}

.result-empty__icon {
  font-size: 46px;
}

.result-empty h2 {
  margin: 0;
  font-size: 21px;
  color: var(--text);
}

.result-empty p {
  margin: 0;
  line-height: 1.6;
  max-width: 420px;
}

.result-empty--warn h2 {
  color: #d97706;
}

.med-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.verify-banner {
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 17px;
  font-weight: 700;
}

.verify-banner.ok {
  background: #e7f7ee;
  color: #16a34a;
}

.verify-banner.wrong {
  background: #fdecec;
  color: #dc2626;
}

.med-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.med-name {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 10px;
}

.med-name strong {
  font-size: 28px;
  color: var(--text);
  line-height: 1.2;
}

.med-spec {
  font-size: 20px;
  color: var(--primary);
  font-weight: 700;
}

.med-chip {
  flex: 0 0 auto;
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
}

.recognized-hint {
  margin: -6px 0 0;
  color: var(--muted);
  font-size: 14px;
}

.med-section h3 {
  margin: 0 0 4px;
  font-size: 17px;
  color: var(--primary);
}

.med-section p {
  margin: 0;
  line-height: 1.65;
  color: var(--text);
}

.med-cautions {
  margin: 0;
  padding-left: 22px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  line-height: 1.6;
}

.med-note {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff8e6;
  color: #92600a;
  font-size: 14px;
  line-height: 1.6;
}

.med-source {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}

.result-actions {
  display: flex;
  gap: 10px;
  padding-top: 4px;
}

.result-actions .el-button {
  flex: 1;
  min-height: 52px;
  font-size: 18px;
  margin: 0;
}

@media (max-width: 768px) {
  .photo-shell {
    grid-template-columns: 1fr;
    grid-auto-rows: min-content;
    overflow-y: auto;
  }
}
</style>
