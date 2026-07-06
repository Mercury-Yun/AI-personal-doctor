<template>
  <section class="compact-page photo-page">
    <div class="compact-page__head photo-page__head">
      <h1>{{ isReminderVerifySession ? '用药确认' : '拍照问药' }}</h1>
      <el-select v-model="selectedUserId" placeholder="选择患者" @change="handleUserChange">
        <el-option v-for="user in users" :key="user.id" :label="user.name" :value="user.id" />
      </el-select>
    </div>

    <div class="compact-page__body photo-shell">
      <aside class="preview-panel card">
        <div class="preview-box">
          <img v-if="previewUrl" :src="previewUrl" alt="最近拍摄的药盒照片" />
          <div v-else class="preview-placeholder">
            <strong>药盒预览</strong>
            <p>拍一次照后可连续追问</p>
          </div>
        </div>
        <p v-if="previewMeta" class="preview-meta">{{ previewMeta }}</p>
      </aside>

      <main class="chat-panel card">
        <div class="chat-titlebar">
          <strong>识别结果</strong>
          <div class="chat-titlebar__meta">
            <span v-if="sessionStatusLabel" class="session-pill">{{ sessionStatusLabel }}</span>
            <el-button v-if="photoSessionActive" link type="danger" @click="handleStopSession">结束</el-button>
            <span v-if="phaseLabel && phase.value !== 'answering'" class="phase-label">{{ phaseLabel }}</span>
          </div>
        </div>

        <div ref="messageListRef" class="message-list">
          <div v-if="!messages.length && isReminderVerifySession" class="welcome-card">
            <h2>核对今天该吃的药</h2>
            <p>
              请把<strong>提醒里说的那盒药</strong>对准摄像头拍照。
              若核对<strong>不对</strong>，换好正确的药盒后，点下方<strong>「重新拍照核对」</strong>。
              核对<strong>正确</strong>后可继续问怎么吃、注意事项等。说「<strong>退出</strong>」返回首页。
            </p>
          </div>
          <div v-else-if="!messages.length" class="welcome-card">
            <h2>对准药盒拍照</h2>
            <p>
              点击下方<strong>「拍照问药」</strong>开始，或回首页喊「豆包」。
              先拍<strong>一张</strong>药盒照，然后可连续问「怎么吃」「有副作用吗」等，<strong>不会重复拍照</strong>。
              换一盒药时说「<strong>换一个</strong>」会再拍。说「<strong>切换问诊</strong>」或问一般健康问题可转到问诊。
              说「<strong>退出</strong>」结束并<strong>返回首页</strong>。
            </p>
          </div>
          <div v-for="item in messages" :key="item.localId || item.id" class="message-row" :class="item.role">
            <div class="bubble">
              <p>{{ item.content }}</p>
              <time>{{ formatTime(item.created_at) }}</time>
            </div>
          </div>
          <div v-if="loading && !streamingText" class="message-row assistant">
            <div class="bubble loading-bubble">{{ statusHint }}</div>
          </div>
        </div>

        <div v-if="references.length" class="reference-list">
          <span>参考：</span>
          <el-tag v-for="item in references" :key="item.title">{{ item.title }}</el-tag>
        </div>

        <div class="input-bar photo-actions">
          <el-button
            class="photo-ask-btn"
            type="primary"
            :loading="loading"
            :disabled="photoBtnDisabled"
            @click="captureAndAsk"
          >
            {{ btnLabel }}
          </el-button>
          <details class="text-input-toggle">
            <summary>文字提问（可选）</summary>
            <div class="text-input-row">
              <el-input
                v-model="question"
                type="textarea"
                :rows="1"
                :autosize="{ minRows: 1, maxRows: 2 }"
                resize="none"
                placeholder="例如：这个药要怎么吃？"
              />
            </div>
          </details>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { createChatSession, getChatHistory, getChatSessions, streamVisionChatMessage } from '../api/chat'
import {
  ackReminder,
  capturePhoto,
  cancelWakeSession,
  classifyPhotoSessionAction,
  getCameraPreviewUrl,
  listenVoice,
  pauseReminderTts,
  pauseWakeListening,
  resumeReminderTts,
  resumeWakeListening,
  speakText,
} from '../api/device'
import { getUsers } from '../api/users'
import {
  emitVoiceStop,
  getVoiceSessionBusy,
  isSessionExitPhrase,
  prepareForPhotoCapture,
  quickPreparePhotoCapture,
  releaseVoiceSession,
  stopAllTts,
  syncVoiceSessionBusy,
  VOICE_STOP_EVENT,
  waitForTtsIdle,
} from '../utils/voiceSession'

const DEFAULT_QUESTION = '请读取药盒包装上可见的药品名称，并说明用法用量和注意事项。'
const PHOTO_HOLD_MS = 2000
const PHOTO_HANDOFF_GUARD_MS = 180000
const CAPTURE_READY_SPEECH = '请把药盒对准摄像头，拿稳，两秒后拍照'
const CAPTURE_DONE_SPEECH = '拍好了，请说出您想问的问题'
const RECAPTURE_READY_SPEECH = '请把新药盒对准摄像头，两秒后拍照'
const SESSION_INTRO_SPEECH =
  '开始问药。我先拍一张药盒照片，然后您可以连续提问。换一盒药说换一个，说切换问诊可以转到问诊，说退出返回首页。'
const INITIAL_LISTEN_HINT = '请说出您想问的问题。说切换问诊可以转到问诊，说退出返回首页'
const FOLLOWUP_LISTEN_HINT =
  '请继续问药。换一盒说换一个，说切换问诊可以转到问诊，说退出返回首页'
const RECAPTURE_LISTEN_HINT = '请说出您想问的问题。说切换问诊可以转到问诊，说退出返回首页'
const REMINDER_CAPTURE_SPEECH = '请拿今天该吃的药盒，对准摄像头，两秒后拍照'
const REMINDER_RETAKE_CAPTURE_SPEECH = '请拿正确的药盒对准摄像头，两秒后拍照'
const REMINDER_WRONG_BUTTON_SPEECH = '这盒药不对，请换正确的药盒，然后点击下方重新拍照按钮'
const REMINDER_WRONG_REPEAT_SPEECH = '还是不对，请换正确的药盒，再点下方重新拍照按钮'
const REMINDER_POST_VERIFY_SPEECH = '核对正确。'
const REMINDER_POST_VERIFY_LISTEN = '请继续提问，例如怎么吃、注意什么；说退出返回首页'
const REMINDER_SESSION_TTS_PAUSE_SEC = 900
const EMPTY_LISTEN_HINT = '没听到您说话。请继续提问，说切换问诊可以转到问诊，或说退出返回首页'
const SESSION_END_SPEECH = '好的，已结束问药，返回首页'
const SWITCH_TO_DOCTOR_SPEECH = '好的，为您切换到问诊'
const SWITCH_TO_DOCTOR_LISTEN_SPEECH = '好的，为您切换到问诊，请说您的问题'

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

const router = useRouter()
const wakeSessionInFlight = inject('wakeSessionInFlight', ref(false))

const users = ref([])
const selectedUserId = ref(null)
const selectedSessionId = ref(null)
const messages = ref([])
const question = ref('')
const loading = ref(false)
const phase = ref('idle')
const references = ref([])
const previewUrl = ref('')
const previewMeta = ref('')
const messageListRef = ref(null)
const photoSessionActive = ref(false)
const hasCapturedPhoto = ref(false)
const reminderVerifyContext = ref(null)
const reminderPostVerify = ref(false)
const reminderNeedsRecapture = ref(false)
const reminderWrongNotified = ref(false)
let sessionEpoch = 0
let turnLock = false
let emptyListenStreak = 0
let followupTimer = null
let streamAbortController = null
let captureAbortController = null
let routeLeaveHandled = false

const phaseLabel = computed(() => {
  if (phase.value === 'speaking') return '请听提示...'
  if (phase.value === 'capturing') return '请拿稳药盒...'
  if (phase.value === 'listening') return '请说话'
  if (phase.value === 'answering') return '回答中'
  return ''
})
const isReminderVerifySession = computed(() => Boolean(reminderVerifyContext.value))
const isReminderPostVerifySession = computed(() => reminderPostVerify.value)

const buildReminderVerifyQuestion = () => {
  const r = reminderVerifyContext.value
  if (!r) return ''
  const name = r.name || '该药'
  const dosage = r.dosage ? ` ${r.dosage}` : ''
  return `这是不是该吃的药？今天应该吃 ${name}${dosage}。`
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
  if (normalized.includes(expected)) return true
  const core = normalizeMedicineCore(expected)
  return core.length >= 2 && normalized.includes(core)
}

const isCorrectMedicineAnswer = (text, expectedName = '') => {
  const normalized = (text || '').trim()
  if (!normalized) return false
  if (/不是该吃|不是这个药|不是今天|不是提醒|别吃|不要服|先别吃|不能服|请勿/.test(normalized)) {
    return false
  }
  const expected = (expectedName || reminderVerifyContext.value?.name || '').trim()
  if (expected && medicineNameMatches(normalized, expected)) {
    return true
  }
  if (/是该吃|是这个药|可以服用|请按时|没问题|药品正确|确认无误|是，是该|对的，是该/.test(normalized)) {
    return true
  }
  return false
}

const isWrongMedicineAnswer = (text, expectedName = '') => {
  const normalized = (text || '').trim()
  if (!normalized) return false
  if (isCorrectMedicineAnswer(normalized, expectedName)) return false
  if (/不是该吃|不是这个药|不是今天|不是提醒|别吃|不要服|先别吃|不能服|请勿/.test(normalized)) {
    return true
  }
  if (normalized.startsWith('不是') && !/是该吃|是这个药/.test(normalized)) {
    return true
  }
  return false
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

const keepReminderSessionQuiet = () => {
  if (isReminderVerifySession.value || reminderVerifyContext.value) {
    void pauseReminderTts(REMINDER_SESSION_TTS_PAUSE_SEC).catch(() => {})
  }
}

const sessionStatusLabel = computed(() => {
  if (!photoSessionActive.value && !loading.value) return ''
  if (isReminderVerifySession.value) {
    if (phase.value === 'answering') return '核对中'
    if (phase.value === 'capturing') return '拍照中'
    if (hasCapturedPhoto.value && reminderNeedsRecapture.value) {
      return '用药确认 · 请换盒后点下方重新拍照'
    }
    if (hasCapturedPhoto.value) return '用药确认 · 核对中'
    return '用药确认 · 请对准今天该吃的药'
  }
  if (phase.value === 'answering') return '问药中'
  if (phase.value === 'listening') return '录音中'
  if (phase.value === 'capturing') return '拍照中'
  if (phase.value === 'speaking') return '问药中'
  if (hasCapturedPhoto.value) return '问药中 · 说「切换问诊」转问诊 · 说「退出」回首页'
  return '问药中 · 说「切换问诊」转问诊 · 说「退出」取消'
})
const hasTypedQuestion = computed(() => question.value.trim().length > 0)
const btnLabel = computed(() => {
  if (wakeSessionInFlight.value) return '唤醒占用中...'
  if (loading.value) {
    if (phase.value === 'speaking') return '请听提示...'
    if (phase.value === 'capturing') return '拍照中...'
    if (phase.value === 'listening') return '录音中...'
    if (phase.value === 'answering') return '回答中...'
  }
  if (photoSessionActive.value && hasCapturedPhoto.value) {
    if (reminderNeedsRecapture.value && isReminderVerifySession.value) {
      return '重新拍照核对'
    }
    return hasTypedQuestion.value ? '发送文字问题' : '继续问药'
  }
  if (photoSessionActive.value && !hasCapturedPhoto.value) {
    return '问药进行中...'
  }
  return '拍照问药'
})
const photoBtnDisabled = computed(() => {
  if (loading.value) return true
  if (wakeSessionInFlight.value && !photoSessionActive.value) return true
  return false
})
const statusHint = computed(() => {
  if (isReminderVerifySession.value) {
    if (phase.value === 'capturing') return '正在拍照，请拿稳药盒…'
    if (phase.value === 'answering') return '正在核对药盒…'
    if (reminderNeedsRecapture.value) return '请换正确的药盒，然后点击下方「重新拍照核对」'
    if (isReminderPostVerifySession.value) return '请提问，或说退出返回首页'
  }
  if (phase.value === 'speaking') return '正在播放提示，请把药盒对准摄像头...'
  if (phase.value === 'capturing') return '正在对焦拍照，请拿稳药盒约 5～15 秒…'
  if (phase.value === 'listening') return '请说出您的问题，说完稍停 2 秒即可...'
  if (phase.value === 'answering') return 'AI 正在根据当前药盒照片回答...'
  return '正在处理...'
})
const streamingText = computed(() => messages.value.some((item) => item.role === 'assistant' && item.content))

const formatTime = (value) =>
  value
    ? new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

const scrollToBottom = async () => {
  await nextTick()
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

const loadUsers = async () => {
  const { data } = await getUsers()
  users.value = data
  if (data.length) {
    selectedUserId.value = data[0].id
    await ensureSession()
  }
}

const handleUserChange = async () => {
  teardownPhotoSession()
  selectedSessionId.value = null
  messages.value = []
  references.value = []
  hasCapturedPhoto.value = false
  previewUrl.value = ''
  previewMeta.value = ''
  await ensureSession()
}

const ensureSession = async () => {
  if (!selectedUserId.value) return
  try {
    const { data } = await getChatSessions(selectedUserId.value)
    if (data.length) {
      selectedSessionId.value = data[0].id
      const { data: history } = await getChatHistory(data[0].id)
      messages.value = history
      scrollToBottom()
      return
    }
    const { data: created } = await createChatSession({ user_id: selectedUserId.value })
    selectedSessionId.value = created.id
    messages.value = []
  } catch {
    ElMessage.error('会话加载失败，请确认后端服务已启动')
  }
}

const newSession = async () => {
  const { data } = await createChatSession({ user_id: selectedUserId.value })
  selectedSessionId.value = data.id
  messages.value = []
  references.value = []
}

const formatError = (error) => {
  const detail = error?.response?.data?.detail || error?.message
  if (typeof detail === 'string' && detail.trim()) {
    if (/timeout|time exceeded|timed out/i.test(detail)) {
      return '处理超时，请稍等几秒后点「继续问药」或重新拍照'
    }
    return detail
  }
  if (error?.code === 'ECONNABORTED') return '处理超时，请稍等几秒后重试'
  return '拍照问药失败，请再试一次'
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const isLiveSession = (epoch) => epoch === sessionEpoch && photoSessionActive.value

const clearFollowupTimer = () => {
  if (followupTimer) {
    clearTimeout(followupTimer)
    followupTimer = null
  }
}

const abortInflightRequests = () => {
  if (streamAbortController) {
    streamAbortController.abort()
    streamAbortController = null
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
  sessionStorage.setItem('photo_session_handoff', String(Date.now()))
}

const isPhotoHandoffActive = () => {
  const handoff = sessionStorage.getItem('photo_session_handoff')
  return handoff && Date.now() - Number(handoff) < PHOTO_HANDOFF_GUARD_MS
}

const isPhotoCapturePhase = () =>
  photoSessionActive.value &&
  (loading.value || phase.value === 'capturing' || phase.value === 'speaking')

const shouldStopPhotoOnLeave = () =>
  photoSessionActive.value || loading.value || phase.value !== 'idle'

const finalizePhotoRouteLeave = () => {
  if (routeLeaveHandled || isPhotoHandoffActive()) return
  routeLeaveHandled = true
  if (shouldStopPhotoOnLeave()) {
    teardownPhotoSession({ markInterrupted: true })
  }
  releaseVoiceSession({ cancelWake: false })
}

const teardownPhotoSession = ({ markInterrupted = false } = {}) => {
  const wasReminderVerify = Boolean(reminderVerifyContext.value)
  sessionEpoch += 1
  clearFollowupTimer()
  abortInflightRequests()
  photoSessionActive.value = false
  turnLock = false
  loading.value = false
  phase.value = 'idle'
  emptyListenStreak = 0
  syncVoiceBusyFlag(false)
  reminderVerifyContext.value = null
  reminderPostVerify.value = false
  reminderNeedsRecapture.value = false
  reminderWrongNotified.value = false
  if (wasReminderVerify) {
    void resumeReminderTts().catch(() => {})
  }
  void resumeWakeListening().catch(() => {})
  if (markInterrupted) {
    sessionStorage.setItem('photo_session_interrupted', String(Date.now()))
  }
}

const onGlobalVoiceStop = () => {
  if (isPhotoHandoffActive() || isPhotoCapturePhase()) {
    return
  }
  if (photoSessionActive.value || loading.value) {
    teardownPhotoSession()
  }
}

const resetPageState = () => {
  teardownPhotoSession()
  hasCapturedPhoto.value = false
  previewUrl.value = ''
  previewMeta.value = ''
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

const stopPhotoSession = () => {
  teardownPhotoSession()
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
  clearFollowupTimer()
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
  sessionStorage.setItem('wake_chat_payload', JSON.stringify(payload))
  await router.push('/doctor-chat')
}

const exitPhotoSession = async ({ speech = SESSION_END_SPEECH, message = '已结束问药', goHome = true } = {}) => {
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
  if (goHome) {
    await router.push('/dashboard')
  }
}

const handleStopSession = async () => {
  if (!photoSessionActive.value && !loading.value) return
  await exitPhotoSession()
}

const ensureChatSession = async () => {
  if (!selectedUserId.value) {
    ElMessage.warning('请先选择患者')
    return false
  }
  if (!selectedSessionId.value) {
    await newSession()
  }
  return true
}

const capturePhotoWithTimeout = async (ms = 45000, epoch = sessionEpoch) => {
  const timeoutMs = Math.max(ms, 35000)
  captureAbortController = new AbortController()
  const timer = window.setTimeout(() => captureAbortController.abort(), timeoutMs)
  try {
    const result = await capturePhoto({ signal: captureAbortController.signal })
    if (!isLiveSession(epoch)) {
      const err = new Error('问药已取消')
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
  voicePrepDone = false,
  epoch = sessionEpoch,
} = {}) => {
  await quickPreparePhotoCapture({ voicePrepDone })
  if (handoff || reminderVerify || isReminderVerifySession.value) {
    keepReminderSessionQuiet()
  }
  refreshPhotoHandoff()

  let spokeCapturePrompt = false
  if (recapture) {
    phase.value = 'speaking'
    scrollToBottom()
    try {
      await speakText(RECAPTURE_READY_SPEECH, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('问药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else if (reminderVerify) {
    phase.value = 'speaking'
    scrollToBottom()
    try {
      await speakText(retake ? REMINDER_RETAKE_CAPTURE_SPEECH : REMINDER_CAPTURE_SPEECH, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('问药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else if (!handoff) {
    const prompt = compact ? '请把药盒对准摄像头，两秒后拍照' : CAPTURE_READY_SPEECH
    phase.value = 'speaking'
    scrollToBottom()
    try {
      await speakText(prompt, true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('问药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else if (fastHandoff) {
    phase.value = 'speaking'
    scrollToBottom()
    try {
      await speakText('请把药盒对准摄像头，两秒后拍照', true)
      spokeCapturePrompt = true
    } catch {
      /* 提示语失败不阻断拍照 */
    }
    if (!isLiveSession(epoch)) {
      const err = new Error('问药已取消')
      err.name = 'SessionAbort'
      throw err
    }
  } else {
    phase.value = 'capturing'
    scrollToBottom()
  }

  phase.value = 'capturing'
  scrollToBottom()
  if (spokeCapturePrompt) {
    await waitForTtsIdle(8000)
    await sleep(PHOTO_HOLD_MS)
  } else {
    await sleep(handoff ? 400 : PHOTO_HOLD_MS)
  }
  refreshPhotoHandoff()
  if (!isLiveSession(epoch)) {
    const err = new Error('问药已取消')
    err.name = 'SessionAbort'
    throw err
  }

  await cancelWakeSession().catch(() => {})
  await pauseWakeListening(60).catch(() => {})
  await sleep(300)

  let lastError = null
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      refreshPhotoHandoff()
      const { data } = await capturePhotoWithTimeout(45000, epoch)
      previewUrl.value = getCameraPreviewUrl()
      previewMeta.value = data.width && data.height ? `${data.width} × ${data.height}` : '已拍照'
      hasCapturedPhoto.value = true
      phase.value = 'idle'
      scrollToBottom()
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
        String(error?.response?.data?.detail || error?.message || '')
      )
      if (attempt < 2 && (busy || cameraFail)) {
        ElMessage.warning(
          cameraFail ? '摄像头恢复中，5 秒后重试…' : '语音引擎正忙，3 秒后重试拍照…'
        )
        await cancelWakeSession().catch(() => {})
        await sleep(cameraFail ? 5000 : 3000)
        continue
      }
      if (error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError' || error?.name === 'AbortError') {
        throw new Error('拍照超时，请点「重新拍照核对」或返回首页再试')
      }
      throw error
    }
  }
  if (lastError) {
    throw lastError
  }

  if (!skipDoneSpeech) {
    phase.value = 'speaking'
    await speakText(CAPTURE_DONE_SPEECH, true)
    await waitForTtsIdle()
    await sleep(500)
  }
}

const listenAfterCapturePrompt = async (epoch = sessionEpoch) => {
  phase.value = 'listening'
  scrollToBottom()
  const { data } = await listenVoice(false, '')
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
}

const listenQuestion = async (speakFirst = '', epoch = sessionEpoch) => {
  phase.value = 'listening'
  scrollToBottom()
  const { data } = await listenVoice(false, speakFirst)
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
}

const answerQuestion = async (
  questionText,
  label = '拍照问药',
  epoch = sessionEpoch,
  { speak = true } = {}
) => {
  if (!isLiveSession(epoch)) return { kind: 'abort' }

  const finalQuestion = (questionText || '').trim() || DEFAULT_QUESTION
  messages.value.push({
    localId: Date.now(),
    role: 'user',
    content: `[${label}] ${finalQuestion}`,
    created_at: new Date().toISOString(),
  })
  phase.value = 'answering'
  scrollToBottom()

  const assistantLocalId = `${Date.now()}-assistant`
  messages.value.push({
    localId: assistantLocalId,
    role: 'assistant',
    content: '',
    created_at: new Date().toISOString(),
  })
  scrollToBottom()

  abortInflightRequests()
  streamAbortController = new AbortController()

  let reminderAck = null
  try {
    if (speak) {
      await stopAllTts(8000)
    }
    await streamVisionChatMessage(
      {
        session_id: selectedSessionId.value,
        user_id: selectedUserId.value,
        question: finalQuestion,
        speak,
      },
      {
        onMeta: (data) => {
          references.value = data.references || []
        },
        onDelta: (text) => {
          const msg = messages.value.find((item) => item.localId === assistantLocalId)
          if (msg) msg.content += text
          scrollToBottom()
        },
        onDone: (data) => {
          const msg = messages.value.find((item) => item.localId === assistantLocalId)
          if (msg && data.answer) msg.content = data.answer
          if (data.reminder_ack) reminderAck = data.reminder_ack
        },
      },
      { signal: streamAbortController.signal }
    )
  } catch (error) {
    if (error?.name === 'AbortError' || !isLiveSession(epoch)) {
      return { kind: 'abort' }
    }
    throw error
  } finally {
    streamAbortController = null
  }

  if (!isLiveSession(epoch)) return { kind: 'abort' }

  const assistantMsg = messages.value.find((item) => item.localId === assistantLocalId)
  const assistantText = (assistantMsg?.content || '').trim()
  const expectedMedicineName = reminderVerifyContext.value?.name || ''

  if (
    isReminderVerifySession.value &&
    !reminderAck &&
    isCorrectMedicineAnswer(assistantText, expectedMedicineName)
  ) {
    const ctx = reminderVerifyContext.value
    if (ctx?.medication_id) {
      try {
        await ackReminder(ctx.medication_id, ctx.take_time)
        reminderAck = { name: ctx.name || expectedMedicineName }
      } catch {
        /* backend may have already acked */
      }
    }
  }

  if (reminderAck) {
    reminderNeedsRecapture.value = false
    reminderWrongNotified.value = false
    reminderVerifyContext.value = null
    reminderPostVerify.value = true
    ElMessage.success(`已确认服用：${reminderAck.name || '该药'}`)
    try {
      await speakText(REMINDER_POST_VERIFY_SPEECH, true)
      await waitForTtsIdle(15000)
    } catch {
      /* optional */
    }
    scheduleAutoFollowup(epoch, 1000)
    return { kind: 'verified_continue' }
  }

  if (isReminderVerifySession.value && isWrongMedicineAnswer(assistantText, expectedMedicineName)) {
    question.value = ''
    await notifyReminderWrong(epoch)
    return { kind: 'verify_wrong' }
  }

  question.value = ''
  await waitForTtsIdle()
  if (!isLiveSession(epoch)) return { kind: 'abort' }
  return { kind: 'ok' }
}

const resolveInitialQuestion = async (preset = '', epoch = sessionEpoch) => {
  const typed = (preset || question.value || '').trim()
  if (typed) {
    if (isSessionExitPhrase(typed)) return { kind: 'exit' }
    return { kind: 'ok', text: typed }
  }
  let listened = await listenAfterCapturePrompt(epoch)
  if (listened.kind === 'empty') {
    try {
      await speakText('没听到您的问题，请再说一遍', true)
      await waitForTtsIdle()
      await sleep(400)
    } catch {
      /* optional */
    }
    if (!isLiveSession(epoch)) return { kind: 'abort' }
    listened = await listenAfterCapturePrompt(epoch)
  }
  return listened
}

const runInitialTurnCore = async (
  presetQuestion = '',
  epoch = sessionEpoch,
  { fastHandoff = false, voicePrepDone = false } = {}
) => {
  if (!(await ensureChatSession())) {
    return { kind: 'abort' }
  }
  references.value = []
  emptyListenStreak = 0
  const preset = (presetQuestion || '').trim()
  const fromHandoff = Boolean(preset)

  await capturePhotoOnly({
    skipDoneSpeech: fromHandoff,
    compact: fromHandoff || fastHandoff,
    handoff: fromHandoff || fastHandoff,
    fastHandoff,
    voicePrepDone,
    reminderVerify: isReminderVerifySession.value,
    epoch,
  })
  if (!isLiveSession(epoch)) return { kind: 'abort' }

  if (fromHandoff) {
    if (isSessionExitPhrase(preset)) {
      return { kind: 'exit' }
    }
    const initialAction = await resolvePhotoSessionAction(preset)
    if (initialAction === 'doctor') {
      await switchToDoctorChat(preset)
      return { kind: 'doctor' }
    }
    await waitForTtsIdle(15000)
    const answered = await answerQuestion(
      preset,
      isReminderVerifySession.value ? '用药确认' : '拍照问药',
      epoch,
      { speak: !isReminderVerifySession.value }
    )
    if (answered.kind === 'verified_continue') return { kind: 'verified_continue' }
    if (answered.kind === 'verify_wrong') return { kind: 'verify_wrong' }
    if (answered.kind === 'verified') return { kind: 'verified' }
    return answered.kind === 'abort' ? { kind: 'abort' } : { kind: 'ok' }
  }

  const resolved = await resolveInitialQuestion(presetQuestion, epoch)
  if (!isLiveSession(epoch)) return { kind: 'abort' }
  if (resolved.kind === 'abort') return { kind: 'abort' }
  if (resolved.kind === 'exit') return { kind: 'exit' }
  if (resolved.kind === 'empty') {
    ElMessage.info('没听到您的问题，请继续说话')
    return { kind: 'empty' }
  }
  const initialAction = await resolvePhotoSessionAction(resolved.text)
  if (initialAction === 'doctor') {
    await switchToDoctorChat(resolved.text)
    return { kind: 'doctor' }
  }
  const answered = await answerQuestion(resolved.text, '拍照问药', epoch)
  return answered.kind === 'abort' ? { kind: 'abort' } : { kind: 'ok' }
}

const runInitialTurn = async (presetQuestion = '', epoch = sessionEpoch, options = {}) =>
  withTurnLock(() => runInitialTurnCore(presetQuestion, epoch, options))

const resolvePhotoSessionAction = async (text) => {
  try {
    const { data } = await classifyPhotoSessionAction(text, true)
    return data.action || 'followup'
  } catch {
    return 'followup'
  }
}

const runReminderRecapture = async (epoch = sessionEpoch) => {
  if (!isLiveSession(epoch)) return { kind: 'abort' }
  clearFollowupTimer()
  keepReminderSessionQuiet()
  previewUrl.value = ''
  previewMeta.value = ''
  hasCapturedPhoto.value = false
  await capturePhotoOnly({
    handoff: true,
    skipDoneSpeech: true,
    reminderVerify: true,
    retake: true,
    epoch,
  })
  if (!isLiveSession(epoch)) return { kind: 'abort' }
  const verifyQ = buildReminderVerifyQuestion()
  const answered = await answerQuestion(verifyQ, '用药确认', epoch, { speak: false })
  if (answered.kind === 'verified_continue') {
    return { kind: 'verified_continue' }
  }
  if (answered.kind === 'verify_wrong') {
    return { kind: 'verify_wrong' }
  }
  if (answered.kind === 'abort') return { kind: 'abort' }
  return { kind: 'ok' }
}

const runFollowupTurnCore = async (epoch = sessionEpoch) => {
  if (!isLiveSession(epoch)) return { kind: 'abort' }
  if (!(await ensureChatSession())) {
    return { kind: 'abort' }
  }
  if (!hasCapturedPhoto.value) {
    return runInitialTurnCore('', epoch)
  }

  await waitForTtsIdle()
  if (!isLiveSession(epoch)) return { kind: 'abort' }

  if (reminderNeedsRecapture.value && isReminderVerifySession.value) {
    ElMessage.info('请先换正确的药盒，再点击下方「重新拍照核对」')
    return { kind: 'wait_button' }
  }

  const typed = question.value.trim()
  let heard = typed
  if (!heard) {
    const listenHint = isReminderPostVerifySession.value ? REMINDER_POST_VERIFY_LISTEN : FOLLOWUP_LISTEN_HINT
    const listened = await listenQuestion(listenHint, epoch)
    if (!isLiveSession(epoch)) return { kind: 'abort' }
    if (listened.kind === 'abort') return listened
    if (listened.kind === 'exit') return { kind: 'exit' }
    if (listened.kind === 'empty') {
      emptyListenStreak += 1
      if (emptyListenStreak >= 3) {
        await speakText(EMPTY_LISTEN_HINT, true)
        emptyListenStreak = 0
      }
      return { kind: 'empty' }
    }
    heard = listened.text
  } else if (isSessionExitPhrase(heard)) {
    return { kind: 'exit' }
  }
  if (!isLiveSession(epoch)) return { kind: 'abort' }
  emptyListenStreak = 0

  const action = await resolvePhotoSessionAction(heard)
  if (action === 'doctor') {
    await switchToDoctorChat(heard)
    return { kind: 'doctor' }
  }
  if (action === 'recapture') {
    await capturePhotoOnly({ recapture: true, epoch })
    if (!isLiveSession(epoch)) return { kind: 'abort' }
    const next = await listenAfterCapturePrompt(epoch)
    if (!isLiveSession(epoch)) return { kind: 'abort' }
    if (next.kind === 'abort') return next
    if (next.kind === 'exit') return { kind: 'exit' }
    const q = next.kind === 'ok' ? next.text : DEFAULT_QUESTION
    const answered = await answerQuestion(q, '换盒问药', epoch)
    return answered.kind === 'abort' ? { kind: 'abort' } : { kind: 'ok' }
  }

  const followupLabel = isReminderPostVerifySession.value ? '用药追问' : '追问'
  const answered = await answerQuestion(heard, followupLabel, epoch)
  return answered.kind === 'abort' ? { kind: 'abort' } : { kind: 'ok' }
}

const runFollowupTurn = async (epoch = sessionEpoch) => withTurnLock(() => runFollowupTurnCore(epoch))

const scheduleAutoFollowup = (epoch, delayMs = 800) => {
  if (!isLiveSession(epoch)) return
  clearFollowupTimer()
  followupTimer = window.setTimeout(() => {
    followupTimer = null
    runAutoFollowupOnce(epoch)
  }, delayMs)
}

const runAutoFollowupOnce = async (epoch = sessionEpoch) => {
  if (!isLiveSession(epoch) || loading.value || turnLock) return

  loading.value = true
  try {
    const result = await runFollowupTurn(epoch)
    if (!isLiveSession(epoch)) return

    if (result?.kind === 'busy') return

    if (result?.kind === 'exit') {
      await exitPhotoSession({ message: '已结束问药' })
      return
    }
    if (result?.kind === 'doctor') {
      return
    }
    if (result?.kind === 'verify_wrong' || result?.kind === 'wait_button') {
      return
    }
    if (result?.kind === 'verified_continue') {
      scheduleAutoFollowup(epoch, 800)
      return
    }
    if (result?.kind === 'empty') {
      if (isReminderPostVerifySession.value) {
        ElMessage.info('没听到。您可以问怎么吃、注意事项，说退出返回首页')
        scheduleAutoFollowup(epoch, 1200)
      } else if (reminderNeedsRecapture.value) {
        ElMessage.info('请先换正确的药盒，再点击下方「重新拍照核对」')
      } else {
        ElMessage.info('没听到声音。请继续说话，说「切换问诊」转问诊，说「退出」返回首页')
        scheduleAutoFollowup(epoch, 1200)
      }
      return
    }
    if (result?.kind === 'ok') {
      scheduleAutoFollowup(epoch, 800)
    }
  } catch (error) {
    if (isLiveSession(epoch)) {
      ElMessage.error(formatError(error))
    }
  } finally {
    if (isLiveSession(epoch)) {
      loading.value = false
      phase.value = 'idle'
      scrollToBottom()
    }
  }
}

const captureAndAsk = async () => {
  if (loading.value) return
  if (wakeSessionInFlight.value && !photoSessionActive.value) {
    ElMessage.info('正在等待唤醒词，请稍等几秒或回首页再试')
    return
  }

  if (photoSessionActive.value && !hasCapturedPhoto.value && !loading.value) {
    teardownPhotoSession()
  }

  if (photoBtnDisabled.value) {
    if (photoSessionActive.value && !hasCapturedPhoto.value) {
      ElMessage.info('问药进行中，请听提示说话，或点右上角「结束」')
    }
    return
  }

  if (photoSessionActive.value && hasCapturedPhoto.value) {
    clearFollowupTimer()
    if (reminderNeedsRecapture.value && isReminderVerifySession.value) {
      loading.value = true
      try {
        const result = await runReminderRecapture(sessionEpoch)
        if (result?.kind === 'verified_continue') {
          scheduleAutoFollowup(sessionEpoch, 800)
        }
      } catch (error) {
        ElMessage.error(formatError(error))
      } finally {
        if (isLiveSession(sessionEpoch)) {
          loading.value = false
          phase.value = 'idle'
        }
      }
      return
    }
    await runAutoFollowupOnce(sessionEpoch)
    return
  }

  if (photoSessionActive.value) return

  const epoch = sessionEpoch
  refreshPhotoHandoff()
  photoSessionActive.value = true
  syncVoiceBusyFlag(true)
  loading.value = true
  try {
    await pauseReminderTts(45).catch(() => {})
    await quickPreparePhotoCapture()
    try {
      await speakText(SESSION_INTRO_SPEECH, true)
    } catch {
      /* intro optional */
    }
    const result = await runInitialTurn('', epoch)
    if (!isLiveSession(epoch)) return
    if (result?.kind === 'exit') {
      await exitPhotoSession({ speech: '好的，已取消', message: '已取消问药' })
      return
    }
    if (result?.kind === 'abort') {
      teardownPhotoSession()
      return
    }
    if (result?.kind === 'doctor') {
      return
    }
    if (result?.kind === 'empty') {
      scheduleAutoFollowup(epoch, 600)
      return
    }
    scheduleAutoFollowup(epoch, 800)
  } catch (error) {
    teardownPhotoSession({ markInterrupted: true })
    ElMessage.error(formatError(error))
  } finally {
    if (isLiveSession(epoch)) {
      loading.value = false
      phase.value = 'idle'
    } else if (photoSessionActive.value && !hasCapturedPhoto.value) {
      teardownPhotoSession()
    }
    scrollToBottom()
  }
}

const isHandoffPayload = (payload) => Boolean(payload?.fast_handoff || payload?.reminder_verify)

const parseWakePhotoPayload = () => {
  const raw = sessionStorage.getItem('wake_photo_payload')
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

let wakePayloadHandling = false

const handleWakePayload = async (payloadFromEvent = null) => {
  if (wakePayloadHandling) return

  let payload = payloadFromEvent || parseWakePhotoPayload()
  if (!payload) return

  if (wakeSessionInFlight.value && !isHandoffPayload(payload)) {
    ElMessage.info('正在等待唤醒词，请稍后再试')
    return
  }

  wakePayloadHandling = true
  try {
    refreshPhotoHandoff()
    const preset = (payload.text || '').trim()
    if (preset) {
      question.value = preset
    }
    if (payload.user_id) {
      selectedUserId.value = payload.user_id
    }
    reminderVerifyContext.value = payload.reminder_verify || null
    reminderNeedsRecapture.value = false
    reminderWrongNotified.value = false
    keepReminderSessionQuiet()

    const epoch = sessionEpoch
    photoSessionActive.value = true
    syncVoiceBusyFlag(true)
    loading.value = true

    if (payload.user_id) {
      await ensureSession()
    }
    try {
      const result = await runInitialTurn(preset, epoch, {
        fastHandoff: Boolean(payload.fast_handoff),
        voicePrepDone: Boolean(payload.voice_prep_done),
      })
      if (!isLiveSession(epoch)) return
      if (result?.kind === 'busy') {
        sessionStorage.setItem('wake_photo_payload', JSON.stringify(payload))
        teardownPhotoSession()
        ElMessage.info('问药正忙，请稍后再试')
        return
      }
      if (result?.kind === 'exit') {
        sessionStorage.removeItem('wake_photo_payload')
        await exitPhotoSession({ speech: '好的，已取消', message: '已取消问药' })
        return
      }
      if (result?.kind === 'abort') {
        sessionStorage.setItem('wake_photo_payload', JSON.stringify(payload))
        teardownPhotoSession()
        ElMessage.warning('拍照未成功，请再点一次「拍照确认」或下方「拍照问药」')
        return
      }
      if (result?.kind === 'doctor') {
        sessionStorage.removeItem('wake_photo_payload')
        return
      }
      if (result?.kind === 'empty') {
        sessionStorage.removeItem('wake_photo_payload')
        scheduleAutoFollowup(epoch, 600)
        return
      }
      if (result?.kind === 'verified' || result?.kind === 'verified_continue') {
        sessionStorage.removeItem('wake_photo_payload')
        sessionStorage.removeItem('photo_session_handoff')
        if (result?.kind === 'verified_continue') {
          scheduleAutoFollowup(epoch, 800)
        }
        return
      }
      sessionStorage.removeItem('wake_photo_payload')
      sessionStorage.removeItem('photo_session_handoff')
      if (result?.kind === 'verify_wrong') {
        return
      }
      if (result?.kind !== 'verified_continue' && result?.kind !== 'verified') {
        scheduleAutoFollowup(epoch, 800)
      }
    } finally {
      if (isLiveSession(epoch)) {
        loading.value = false
        phase.value = 'idle'
      }
    }
  } catch (error) {
    sessionStorage.setItem('wake_photo_payload', JSON.stringify(payload))
    sessionStorage.removeItem('photo_session_handoff')
    teardownPhotoSession({ markInterrupted: true })
    ElMessage.error(formatError(error))
  } finally {
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
  ElMessage.info('已离开问药页面。若拍照按钮无反应，请等约 10 秒或点右上角「结束」后再试')
}

watch([photoSessionActive, loading], ([active, busy]) => {
  syncVoiceBusyFlag(active || busy)
})

onMounted(async () => {
  window.addEventListener('app-wake-photo', onWakePhotoEvent)
  window.addEventListener(VOICE_STOP_EVENT, onGlobalVoiceStop)
  const pendingPayload = parseWakePhotoPayload()
  if (pendingPayload) {
    hasCapturedPhoto.value = false
    previewUrl.value = ''
    previewMeta.value = ''
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
  await loadUsers()
  if (pendingPayload?.user_id) {
    selectedUserId.value = pendingPayload.user_id
  }
  if (pendingPayload) {
    await handleWakePayload()
  }
})

onBeforeRouteLeave(() => {
  finalizePhotoRouteLeave()
  return true
})

onUnmounted(() => {
  window.removeEventListener('app-wake-photo', onWakePhotoEvent)
  window.removeEventListener(VOICE_STOP_EVENT, onGlobalVoiceStop)
  if (!routeLeaveHandled && !isPhotoHandoffActive()) {
    finalizePhotoRouteLeave()
  }
})
</script>

<style scoped>
.photo-page {
  height: 100%;
  min-height: 0;
}

.photo-page__head {
  margin-bottom: 6px;
}

.photo-page__head h1 {
  font-size: 22px;
}

.photo-page__head .el-select {
  width: 140px;
}

.photo-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 8px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.preview-panel,
.chat-panel {
  min-height: 0;
  overflow: hidden;
}

.preview-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  align-items: stretch;
}

.preview-box {
  width: 100%;
  aspect-ratio: 16 / 9;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 12px;
  background: #eef4fb;
  border: 1px solid var(--border);
}

.preview-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.preview-placeholder {
  text-align: center;
  color: var(--muted);
  padding: 12px;
  width: 100%;
}

.preview-placeholder strong {
  display: block;
  font-size: 20px;
  margin-bottom: 8px;
  color: var(--text);
}

.preview-meta {
  margin: 0;
  text-align: center;
  color: var(--muted);
  font-size: 14px;
}

.chat-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
}

.chat-titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 28px;
}

.chat-titlebar strong {
  font-size: 18px;
}

.chat-titlebar span {
  color: var(--muted);
  font-size: 14px;
}

.chat-titlebar__meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.session-pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: #e8f5ff;
  color: #1677ff;
  font-size: 12px;
  font-weight: 600;
}

.phase-label {
  color: var(--muted);
  font-size: 14px;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 2px;
}

.welcome-card {
  padding: 16px;
  border-radius: 12px;
  background: var(--primary-soft);
}

.welcome-card h2 {
  margin: 0 0 8px;
  font-size: 20px;
}

.welcome-card p {
  margin: 0;
  color: var(--muted);
  line-height: 1.55;
}

.message-row {
  display: flex;
}

.message-row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 92%;
  padding: 10px 12px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid var(--border);
}

.message-row.user .bubble {
  background: var(--primary);
  color: #fff;
  border-color: transparent;
}

.bubble p {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble time {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.72;
}

.loading-bubble {
  color: var(--muted);
}

.reference-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}

.photo-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.photo-ask-btn {
  width: 100%;
  min-height: 52px;
  font-size: 20px;
  font-weight: 600;
}

.text-input-toggle summary {
  cursor: pointer;
  color: var(--muted);
  font-size: 15px;
}

.text-input-row {
  margin-top: 8px;
}
</style>
