<template>
  <section class="compact-page chat-page">
    <div class="doctor-stage">
      <!-- 返回首页 -->
      <button type="button" class="back-fab" aria-label="返回首页" @click="goHome">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
      </button>

      <!-- SOS 紧急求助 -->
      <button type="button" class="sos-fab" :disabled="sosLoading" aria-label="紧急求助" @click="handleSOS">
        SOS
      </button>

      <!-- 状态提示 -->
      <div v-if="statusText" class="stage-status">
        <span class="status-dot" :class="doctorState"></span>
        <span class="status-text">{{ statusText }}</span>
      </div>

      <!-- 数字人 -->
      <div class="doctor-figure" :class="'state-' + doctorState">
        <img
          v-for="state in ['idle', 'listening', 'thinking', 'speaking']"
          :key="state"
          :src="{ idle: doctorIdle, listening: doctorListening, thinking: doctorThinking, speaking: doctorSpeaking }[state]"
          :class="['doctor-img', { active: doctorState === state }]"
          alt="AI医生"
        />
      </div>

      <!-- 当前一轮问答气泡 -->
      <div class="turn-panel">
        <div v-if="!showTurn" class="turn-bubble assistant welcome">
          <img :src="doctorAvatar" class="bubble-avatar" alt="" />
          <p>您好，我是您的AI健康助手。<br />点下面的麦克风，跟我说说哪里不舒服。</p>
        </div>
        <template v-else>
          <div v-if="turnUserText" class="turn-bubble user">
            <p>{{ turnUserText }}</p>
          </div>
          <div v-if="turnAssistantText || turnThinking" class="turn-bubble assistant">
            <img :src="doctorAvatar" class="bubble-avatar" alt="" />
            <p v-if="turnAssistantText">{{ turnAssistantText }}</p>
            <span v-else class="typing-dots"><i></i><i></i><i></i></span>
          </div>
        </template>
      </div>

      <!-- 底部麦克风 -->
      <div class="stage-controls">
        <button
          type="button"
          class="mic-fab"
          :class="{ active: voiceSessionActive || voiceLoading }"
          :disabled="voiceBtnDisabled"
          aria-label="语音提问"
          @click="sendVoiceQuestion"
        >
          <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>
        </button>
        <span class="mic-hint">{{ micHint }}</span>
        <button v-if="voiceSessionActive" type="button" class="end-btn" @click="finishVoiceSession">结束问诊</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import doctorIdle from '../assets/doctor/idle.png'
import doctorListening from '../assets/doctor/listening.png'
import doctorThinking from '../assets/doctor/thinking.png'
import doctorSpeaking from '../assets/doctor/speaking.png'
import doctorAvatar from '../assets/doctor/avatar.png'
import { useWakeStore } from '../stores/wake'
import { createChatSession, streamChatMessage } from '../api/chat'
import { classifyIntent, sendSOS, speakText, stopActiveSpeech, stopVoiceMode } from '../api/device'
import { getUsers } from '../api/users'
import { isPhotoIntent } from '../utils/medicationIntent'
import {
  buildWakeHandoff,
  clearWakePayload,
  isHandoffPayload,
  markPhotoHandoff,
  readWakePayload,
  waitForWakeSessionIdle,
  WAKE_CHAT_KEY,
  WAKE_PHOTO_KEY,
} from '../utils/wakeHandoff'
import { getVoiceSessionBusy, isSessionExitPhrase, listenWithRetry, releaseVoiceSession, syncVoiceSessionBusy, VOICE_STOP_EVENT, waitForTtsIdle } from '../utils/voiceSession'

const router = useRouter()
const wakeSessionInFlight = inject('wakeSessionInFlight', ref(false))

const goHome = () => router.push('/dashboard')

// SOS 紧急求助
const sosLoading = ref(false)
const sosConfirmPending = ref(false)

const handleSOS = async () => {
  if (sosLoading.value) return
  if (!sosConfirmPending.value) {
    sosConfirmPending.value = true
    ElMessage.warning({ message: '再次点击 SOS 确认发送紧急求助', duration: 3000 })
    setTimeout(() => { sosConfirmPending.value = false }, 4000)
    return
  }
  sosConfirmPending.value = false
  sosLoading.value = true
  try {
    const { data } = await sendSOS()
    ElMessage.success(data?.message || '已通知家属')
  } catch (err) {
    const msg = err?.response?.data?.detail || '发送失败，请稍后重试'
    ElMessage.error(msg)
  } finally {
    sosLoading.value = false
  }
}

const users = ref([])
const selectedUserId = ref(null)
const selectedSessionId = ref(null)
const messages = ref([])
const loading = ref(false)
const voiceLoading = ref(false)
const voicePhase = ref('idle')
const references = ref([])
const messageListRef = ref(null)
const showTurn = ref(false)
const voiceSessionActive = ref(false)
const voiceSessionRunning = ref(false)
let voiceSessionGen = 0
let streamAbortController = null
let routeLeaveHandled = false
const VOICE_INTRO_SPEECH = '您好，哪里不舒服跟我说就行'
const VOICE_FOLLOWUP_SPEECH = '嗯，还有别的想问的吗'
const VOICE_EXIT_SPEECH = '好的，您多注意休息，有需要随时叫我'

const bumpVoiceSessionGen = () => {
  voiceSessionGen += 1
  return voiceSessionGen
}

const isVoiceSessionLive = (gen) => gen === voiceSessionGen

const voiceBtnDisabled = computed(
  () =>
    loading.value ||
    voiceLoading.value ||
    voiceSessionActive.value ||
    voiceSessionRunning.value ||
    (Boolean(wakeSessionInFlight.value) && !voiceSessionActive.value && !voiceLoading.value)
)

const doctorState = computed(() => {
  if (voicePhase.value === 'listening') return 'listening'
  if (voicePhase.value === 'thinking' || loading.value) return 'thinking'
  if (voicePhase.value === 'preparing') return 'speaking'
  return 'idle'
})

const statusText = computed(() => ({
  listening: '正在倾听…',
  thinking: '正在思考…',
  speaking: '正在回答…',
}[doctorState.value] || ''))

const micHint = computed(() => {
  if (voiceSessionActive.value) return '对话中，说“退出”可结束'
  if (voiceLoading.value) return '请稍候…'
  return '点击说话'
})

const lastUserMsg = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'user') return messages.value[i]
  }
  return null
})
const lastAssistantMsg = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'assistant') return messages.value[i]
  }
  return null
})
const turnUserText = computed(() => (showTurn.value ? lastUserMsg.value?.content || '' : ''))
const turnAssistantText = computed(() => (showTurn.value ? lastAssistantMsg.value?.content || '' : ''))
const turnThinking = computed(
  () => showTurn.value && !turnAssistantText.value && (loading.value || voiceLoading.value || voicePhase.value === 'thinking')
)

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
  }
}

const newSession = async () => {
  if (!selectedUserId.value) {
    ElMessage.warning('请先选择患者')
    return
  }
  const { data } = await createChatSession({ user_id: selectedUserId.value })
  messages.value = []
  references.value = []
  selectedSessionId.value = data.id
}

const runStreamingChat = async (questionText, speak = false) => {
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

  try {
    await streamChatMessage(
      {
        session_id: selectedSessionId.value,
        user_id: selectedUserId.value,
        question: questionText,
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
        },
      },
      { signal: streamAbortController.signal }
    )
  } catch (error) {
    if (error?.name === 'AbortError') {
      return
    }
    throw error
  } finally {
    streamAbortController = null
  }
}

const formatVoiceError = (error) => {
  const detail = error?.response?.data?.detail || error?.message
  if (typeof detail === 'string' && detail.trim()) return detail
  if (error?.code === 'ECONNABORTED') return '请求超时，请稍后再试'
  return '语音问诊失败，请再试一次'
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const abortInflightRequests = () => {
  if (streamAbortController) {
    streamAbortController.abort()
    streamAbortController = null
  }
}

const isDoctorHandoffActive = () => {
  const handoff = sessionStorage.getItem('photo_session_handoff')
  if (handoff && Date.now() - Number(handoff) < 8000) return true
  return Boolean(sessionStorage.getItem('wake_photo_payload'))
}

const finalizeDoctorRouteLeave = () => {
  if (isDoctorHandoffActive()) return
  if (routeLeaveHandled) return
  routeLeaveHandled = true
  stopVoiceSession()
  releaseVoiceSession({ cancelWake: false })
}

const stopVoiceSession = () => {
  bumpVoiceSessionGen()
  abortInflightRequests()
  voiceSessionActive.value = false
  voiceSessionRunning.value = false
  voiceLoading.value = false
  loading.value = false
  voicePhase.value = 'idle'
  syncVoiceBusyFlag(false)
}

const finishVoiceSession = async ({ goHome = true, announce = true } = {}) => {
  stopVoiceSession()
  releaseVoiceSession({ cancelWake: false })
  if (announce) {
    try {
      await speakText(VOICE_EXIT_SPEECH, true)
    } catch {
      /* ignore */
    }
  }
  if (goHome) {
    ElMessage.success('已结束连续对话')
    await router.push('/dashboard')
  }
}

const onGlobalVoiceStop = () => {
  if (voiceSessionActive.value && (voiceLoading.value || voicePhase.value === 'listening')) {
    return
  }
  if (voiceSessionActive.value || voiceLoading.value) {
    stopVoiceSession()
  }
}

const syncVoiceBusyFlag = (active) => {
  if (active) {
    syncVoiceSessionBusy('doctor')
  } else if (getVoiceSessionBusy() === 'doctor') {
    syncVoiceSessionBusy(null)
  }
}

const switchToPhotoMedicine = async (text) => {
  stopVoiceSession()
  voiceLoading.value = false
  loading.value = false
  voicePhase.value = 'idle'
  await stopActiveSpeech().catch(() => {})
  await stopVoiceMode().catch(() => {})
  await waitForTtsIdle(6000)
  markPhotoHandoff()
  sessionStorage.setItem(
    WAKE_PHOTO_KEY,
    JSON.stringify(
      buildWakeHandoff({
        user_id: selectedUserId.value,
        intent: 'photo',
        text: text || '请读取药盒包装上的药品名称，并说明用法用量和注意事项。',
        voice_prep_done: false,
        from_doctor: true,
      }),
    ),
  )
  syncVoiceSessionBusy('photo')
  await router.push('/photo-medicine')
}

const runOneVoiceTurn = async () => {
  const gen = voiceSessionGen
  const { data: listenData } = await listenWithRetry(false, '')
  if (!isVoiceSessionLive(gen)) {
    return { kind: 'abort' }
  }
  const heard = (listenData.text || '').trim()
  if (!heard) {
    return { kind: 'empty' }
  }
  if (isSessionExitPhrase(heard)) {
    return { kind: 'exit' }
  }

  let intent = 'chat'
  if (isPhotoIntent(heard)) {
    intent = 'photo'
  } else {
    const { data } = await classifyIntent(heard)
    intent = data.intent
  }
  if (!isVoiceSessionLive(gen)) {
    return { kind: 'abort' }
  }
  if (intent === 'photo') {
    return { kind: 'photo', text: heard }
  }

  messages.value.push({
    localId: Date.now(),
    role: 'user',
    content: heard,
    created_at: new Date().toISOString(),
  })
  showTurn.value = true
  voicePhase.value = 'thinking'
  scrollToBottom()
  await runStreamingChat(heard, true)
  if (!isVoiceSessionLive(gen)) {
    return { kind: 'abort' }
  }
  await waitForTtsIdle()
  if (!isVoiceSessionLive(gen)) {
    return { kind: 'abort' }
  }
  return { kind: 'ok' }
}

const startVoiceSessionLoop = (skipIntro = false) => {
  if (voiceSessionRunning.value) return
  voiceSessionActive.value = true
  syncVoiceBusyFlag(true)
  voiceSessionRunning.value = true
  const loopGen = voiceSessionGen
  ;(async () => {
    let turnIndex = skipIntro ? 1 : 0
    try {
      while (voiceSessionActive.value && isVoiceSessionLive(loopGen)) {
        if (loading.value) {
          await sleep(300)
          continue
        }
        if (!selectedUserId.value) break
        if (!selectedSessionId.value) {
          await newSession()
        }

        voiceLoading.value = true
        voicePhase.value = 'preparing'
        scrollToBottom()
        try {
          const prompt = turnIndex === 0 ? VOICE_INTRO_SPEECH : VOICE_FOLLOWUP_SPEECH
          await speakText(prompt, true)
          await waitForTtsIdle()
          if (!voiceSessionActive.value || !isVoiceSessionLive(loopGen)) break
          voicePhase.value = 'listening'
          const result = await runOneVoiceTurn()
          turnIndex += 1
          if (result.kind === 'abort') {
            break
          }
          if (result.kind === 'photo') {
            await switchToPhotoMedicine(result.text)
            break
          }
          if (result.kind === 'exit') {
            await finishVoiceSession()
            break
          }
          if (result.kind === 'empty') {
            ElMessage.warning('抱歉没听清，您能再说一遍吗？')
          }
        } catch (error) {
          ElMessage.error(formatVoiceError(error))
          await sleep(1200)
        } finally {
          voiceLoading.value = false
          if (voiceSessionActive.value && isVoiceSessionLive(loopGen)) {
            voicePhase.value = 'idle'
          }
          scrollToBottom()
        }
      }
    } finally {
      if (isVoiceSessionLive(loopGen)) {
        voiceSessionActive.value = false
        syncVoiceBusyFlag(false)
      }
      voiceSessionRunning.value = false
      voiceLoading.value = false
      voicePhase.value = 'idle'
    }
  })()
}

const sendVoiceQuestion = async () => {
  if (voiceBtnDisabled.value) return
  if (wakeSessionInFlight.value) {
    ElMessage.info('正在等待唤醒词，请稍等几秒或回首页再试')
    return
  }
  if (!selectedUserId.value) {
    ElMessage.warning('请先选择患者')
    return
  }
  if (!selectedSessionId.value) {
    await newSession()
  }

  bumpVoiceSessionGen()
  const turnGen = voiceSessionGen
  voiceLoading.value = true
  voicePhase.value = 'preparing'
  syncVoiceBusyFlag(true)
  scrollToBottom()

  try {
    await speakText('您好，请说说哪里不舒服', true)
    await waitForTtsIdle()
    if (!isVoiceSessionLive(turnGen)) return

    voicePhase.value = 'listening'
    const result = await runOneVoiceTurn()
    if (!isVoiceSessionLive(turnGen)) return

    if (result.kind === 'photo') {
      await switchToPhotoMedicine(result.text)
      return
    }
    if (result.kind === 'empty') {
      ElMessage.warning('没有听清，请听到提示后再说一次')
      return
    }
    if (result.kind === 'exit') {
      await finishVoiceSession()
      return
    }
    if (result.kind === 'ok') {
      startVoiceSessionLoop(true)
    }
  } catch (error) {
    ElMessage.error(formatVoiceError(error))
  } finally {
    if (!voiceSessionRunning.value) {
      voiceLoading.value = false
      voicePhase.value = 'idle'
      if (!voiceSessionActive.value) {
        syncVoiceBusyFlag(false)
      }
    }
    scrollToBottom()
  }
}

const processWakePayload = async (payload) => {
  stopVoiceSession()
  bumpVoiceSessionGen()
  const turnGen = voiceSessionGen
  syncVoiceBusyFlag(true)
  voiceSessionActive.value = true

  if (payload.user_id) {
    selectedUserId.value = payload.user_id
  }
  if (!selectedSessionId.value) {
    await newSession()
  }

  let text = (payload.text || '').trim()
  if (payload.needs_listen || !text) {
    if (!isVoiceSessionLive(turnGen)) return
    voicePhase.value = 'listening'
    voiceLoading.value = true
    scrollToBottom()
    try {
      await waitForTtsIdle(12000)
      if (!isVoiceSessionLive(turnGen)) return
      const { data } = await listenWithRetry(true, '')
      if (!isVoiceSessionLive(turnGen)) return
      text = (data.text || '').trim()
    } catch (error) {
      stopVoiceSession()
      throw error
    } finally {
      voiceLoading.value = false
    }
    if (!text) {
      ElMessage.warning('没有听清，请再说一次')
      if (isVoiceSessionLive(turnGen)) {
        startVoiceSessionLoop(true)
      }
      return
    }
  }

  let photoIntent = isPhotoIntent(text)
  if (!photoIntent) {
    try {
      const { data } = await classifyIntent(text)
      photoIntent = data.intent === 'photo'
    } catch {
      photoIntent = false
    }
  }
  if (!isVoiceSessionLive(turnGen)) return
  if (photoIntent) {
    stopVoiceSession()
    await switchToPhotoMedicine(text)
    return
  }

  messages.value.push({
    localId: Date.now(),
    role: 'user',
    content: text,
    created_at: new Date().toISOString(),
  })
  showTurn.value = true
  voicePhase.value = 'thinking'
  voiceLoading.value = true
  scrollToBottom()
  try {
    await runStreamingChat(text, true)
    await waitForTtsIdle()
    if (isVoiceSessionLive(turnGen)) {
      startVoiceSessionLoop(true)
    }
  } catch (error) {
    stopVoiceSession()
    throw error
  } finally {
    if (!voiceSessionRunning.value) {
      voiceLoading.value = false
      voicePhase.value = 'idle'
    }
  }
}

const handleWakePayload = async (payloadFromEvent = null) => {
  let payload = payloadFromEvent
  let fromStorage = false
  if (!payload) {
    const wakeStore = useWakeStore()
    if (wakeStore.handoff && wakeStore.handoff.routeTarget === 'chat') {
      payload = wakeStore.handoff
      wakeStore.clearHandoff()
    } else {
      payload = readWakePayload(WAKE_CHAT_KEY)
      if (!payload) return
      fromStorage = true
    }
  } else {
    fromStorage = false
  }

  if (fromStorage && wakeSessionInFlight.value) {
    const ready = await waitForWakeSessionIdle(() => wakeSessionInFlight.value, isHandoffPayload(payload) ? 800 : 4000)
    if (!ready && !isHandoffPayload(payload)) {
      ElMessage.info('正在等待唤醒词，请稍后再试')
      return
    }
  }

  try {
    await processWakePayload(payload)
    if (fromStorage) {
      clearWakePayload(WAKE_CHAT_KEY)
    }
  } catch (error) {
    ElMessage.error(formatVoiceError(error))
  } finally {
    if (!voiceSessionActive.value && !voiceSessionRunning.value) {
      voicePhase.value = 'idle'
      voiceLoading.value = false
    }
  }
}

const onWakeChatEvent = (event) => {
  handleWakePayload(event.detail)
}

onMounted(async () => {
  routeLeaveHandled = false
  await loadUsers()
  await handleWakePayload()
  window.addEventListener('app-wake-chat', onWakeChatEvent)
  window.addEventListener(VOICE_STOP_EVENT, onGlobalVoiceStop)
})

onBeforeRouteLeave(() => {
  finalizeDoctorRouteLeave()
  return true
})

onUnmounted(() => {
  window.removeEventListener('app-wake-chat', onWakeChatEvent)
  window.removeEventListener(VOICE_STOP_EVENT, onGlobalVoiceStop)
  stopVoiceSession()
  // 无论是否 handoff，都强制释放 voice busy，确保回首页后能唤醒
  releaseVoiceSession({ cancelWake: false })
  sessionStorage.removeItem(WAKE_CHAT_KEY)
})

watch([voiceSessionActive, voiceLoading], ([active, voiceBusy]) => {
  syncVoiceBusyFlag(active || voiceBusy)
})</script>

<style scoped>
/* ===== 舞台 ===== */
.chat-page {
  height: 100%;
  min-height: 0;
  position: relative;
  overflow: hidden;
  background: radial-gradient(120% 120% at 50% 0%, #ffffff 0%, #eef4ff 55%, #e3edff 100%);
}

.doctor-stage {
  position: relative;
  width: 100%;
  height: 100%;
}

/* ===== 返回首页 ===== */
.back-fab {
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 30;
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.85);
  color: #1677ff;
  box-shadow: 0 2px 10px rgba(31, 80, 160, 0.12);
  cursor: pointer;
  backdrop-filter: blur(8px);
}

.back-fab svg {
  width: 20px;
  height: 20px;
}

.back-fab:hover {
  background: #fff;
}

/* ===== SOS 按钮 ===== */
.sos-fab {
  position: absolute;
  top: 50%;
  left: 60px;
  transform: translateY(-50%);
  z-index: 30;
  width: 76px;
  height: 76px;
  display: grid;
  place-items: center;
  border: 2px solid #dc2626;
  border-radius: 50%;
  background: #dc2626;
  color: #fff;
  font-size: 22px;
  font-weight: 900;
  letter-spacing: 1px;
  cursor: pointer;
  box-shadow: 0 2px 12px rgba(220, 38, 38, 0.4);
  transition: transform 0.15s, box-shadow 0.15s;
}

.sos-fab:active {
  transform: translateY(-50%) scale(0.92);
}

.sos-fab:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ===== 状态提示 ===== */
.stage-status {
  position: absolute;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(8px);
  box-shadow: 0 2px 10px rgba(31, 80, 160, 0.1);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.idle {
  background: #52c41a;
  box-shadow: 0 0 6px rgba(82, 196, 26, 0.5);
  animation: dot-pulse 2s ease-in-out infinite;
}

.status-dot.listening {
  background: #1677ff;
  box-shadow: 0 0 6px rgba(22, 119, 255, 0.5);
  animation: dot-pulse 1s ease-in-out infinite;
}

.status-dot.thinking {
  background: #faad14;
  box-shadow: 0 0 6px rgba(250, 173, 20, 0.5);
  animation: dot-pulse 1.2s ease-in-out infinite;
}

.status-dot.speaking {
  background: #722ed1;
  box-shadow: 0 0 6px rgba(114, 46, 209, 0.5);
  animation: dot-pulse 0.8s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.4); }
}

.status-text {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}

/* ===== 数字人 ===== */
.doctor-figure {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  z-index: 5;
}

.doctor-img {
  position: absolute;
  bottom: 0;
  max-width: 78%;
  max-height: 96%;
  object-fit: contain;
  object-position: bottom center;
  opacity: 0;
  transition: opacity 0.6s ease;
  pointer-events: none;
}

.doctor-img.active {
  opacity: 1;
}

.doctor-figure.state-idle .doctor-img.active {
  animation: breathe 3.5s ease-in-out infinite;
}

.doctor-figure.state-listening .doctor-img.active {
  animation: lean-in 2.5s ease-in-out infinite;
}

.doctor-figure.state-thinking .doctor-img.active {
  animation: sway 3s ease-in-out infinite;
}

.doctor-figure.state-speaking .doctor-img.active {
  animation: pulse-speak 1.8s ease-in-out infinite;
}

@keyframes breathe {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

@keyframes lean-in {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-3px) scale(1.012); }
}

@keyframes sway {
  0%, 100% { transform: translateX(0) rotate(0deg); }
  25% { transform: translateX(-3px) rotate(-0.5deg); }
  75% { transform: translateX(3px) rotate(0.5deg); }
}

@keyframes pulse-speak {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.015); }
}

/* ===== 当前一轮问答气泡 ===== */
.turn-panel {
  position: absolute;
  top: 66px;
  right: 18px;
  z-index: 15;
  width: min(42%, 420px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}

.turn-bubble {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(31, 80, 160, 0.12);
  backdrop-filter: blur(6px);
  animation: bubble-in 0.3s ease;
}

.turn-bubble p {
  margin: 0;
  line-height: 1.55;
  font-size: 15px;
  white-space: pre-wrap;
  word-break: break-word;
}

.turn-bubble.user {
  align-self: flex-end;
  max-width: 92%;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  color: #fff;
  border-bottom-right-radius: 5px;
}

.turn-bubble.assistant {
  align-self: flex-start;
  max-width: 100%;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(219, 228, 240, 0.7);
  color: #1f2937;
  border-bottom-left-radius: 5px;
}

.turn-bubble.welcome p {
  color: #475569;
}

.bubble-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
}

@keyframes bubble-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 0;
}

.typing-dots i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #1677ff;
  opacity: 0.4;
  animation: dot-bounce 1.2s infinite;
}

.typing-dots i:nth-child(2) { animation-delay: 0.2s; }
.typing-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40% { transform: translateY(-4px); opacity: 1; }
}

/* ===== 底部控制 ===== */
.stage-controls {
  position: absolute;
  bottom: 22px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 25;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.mic-fab {
  width: 66px;
  height: 66px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 50%;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  color: #fff;
  cursor: pointer;
  box-shadow: 0 6px 20px rgba(22, 119, 255, 0.35);
  transition: transform 0.15s ease;
}

.mic-fab svg {
  width: 30px;
  height: 30px;
}

.mic-fab:not(:disabled):hover {
  transform: scale(1.06);
}

.mic-fab.active {
  animation: mic-pulse 1.2s infinite;
}

.mic-fab:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@keyframes mic-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(22, 119, 255, 0.4); }
  50% { box-shadow: 0 0 0 12px rgba(22, 119, 255, 0); }
}

.mic-hint {
  font-size: 13px;
  color: #64748b;
  background: rgba(255, 255, 255, 0.7);
  padding: 2px 12px;
  border-radius: 10px;
}

.end-btn {
  padding: 6px 18px;
  border: 1px solid #fda4af;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.9);
  color: #e5484d;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.end-btn:hover {
  background: #fff1f2;
}
</style>
