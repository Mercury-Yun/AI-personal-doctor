<template>
  <section class="compact-page chat-page">
    <div class="compact-page__head chat-page__head">
      <h1>问诊</h1>
      <el-select v-model="selectedUserId" placeholder="选择患者" @change="handleUserChange">
        <el-option v-for="user in users" :key="user.id" :label="user.name" :value="user.id" />
      </el-select>
    </div>

    <div class="compact-page__body chat-shell">
      <aside class="history-panel card">
        <div class="panel-top">
          <div class="panel-top__info">
            <span>会话</span>
            <small>{{ selectedUserName }}</small>
          </div>
          <el-button type="primary" @click="newSession">新建</el-button>
        </div>

        <el-input v-model="sessionKeyword" class="session-search" placeholder="搜索" clearable />

        <div v-if="filteredSessions.length" class="session-list">
          <template v-for="group in groupedSessions" :key="group.title">
            <div v-if="group.items.length" class="session-group-title">{{ group.title }}</div>
            <div
              v-for="session in group.items"
              :key="session.id"
              class="session-item"
              :class="{ active: session.id === selectedSessionId }"
              role="button"
              tabindex="0"
              @click="selectSession(session.id)"
              @keydown.enter="selectSession(session.id)"
            >
              <div class="session-main">
                <strong>{{ session.title }}</strong>
                <span>{{ formatDateTime(session.updated_at) }}</span>
              </div>
              <div class="session-actions" @click.stop>
                <el-button link type="primary" @click="openRename(session)">改</el-button>
                <el-button link type="danger" @click="removeSession(session.id)">删</el-button>
              </div>
            </div>
          </template>
        </div>
        <el-empty v-else description="暂无会话" />
      </aside>

      <main class="chat-panel card">
        <div class="chat-titlebar">
          <strong>{{ currentSession?.title || '请选择或新建问诊' }}</strong>
          <div class="chat-titlebar__meta">
            <span v-if="voiceSessionActive" class="session-pill">连续对话 · 说「退出」回首页</span>
            <el-button v-if="voiceSessionActive" link type="danger" @click="finishVoiceSession">结束</el-button>
            <span v-if="currentSession">更新 {{ formatDateTime(currentSession.updated_at) }}</span>
          </div>
        </div>

        <div ref="messageListRef" class="message-list">
          <div v-if="!messages.length" class="welcome-card">
            <h2>AI 医生助手</h2>
            <p>请点下方<strong>语音提问</strong>开始；<strong>本页不监听「豆包」</strong>，需唤醒请回首页。说「<strong>这是什么</strong>」可切换拍照问药。说「<strong>退出</strong>」结束并返回首页。</p>
          </div>
          <div v-for="item in messages" :key="item.localId || item.id" class="message-row" :class="item.role">
            <div class="bubble">
              <p>{{ item.content }}</p>
              <time>{{ formatTime(item.created_at) }}</time>
            </div>
          </div>
          <div v-if="loading || showLoadingBubble" class="message-row assistant">
            <div class="bubble loading-bubble">{{ statusHint }}</div>
          </div>
        </div>

        <div v-if="references.length" class="reference-list">
          <span>参考：</span>
          <el-tag v-for="item in references" :key="item.title">{{ item.title }}</el-tag>
        </div>

        <div class="input-bar voice-first">
          <el-button
            class="voice-ask-btn"
            type="primary"
            :loading="voiceLoading"
            :disabled="voiceBtnDisabled"
            @click="sendVoiceQuestion"
          >
            {{ voiceBtnLabel }}
          </el-button>
          <details class="text-input-toggle">
            <summary>文字输入（可选）</summary>
            <div class="text-input-row">
              <el-input
                v-model="question"
                type="textarea"
                :rows="1"
                :autosize="{ minRows: 1, maxRows: 2 }"
                resize="none"
                placeholder="输入健康问题"
                @keydown.enter.exact.prevent="sendMessage"
              />
              <el-button type="success" :loading="loading" :disabled="voiceLoading" @click="sendMessage">发送</el-button>
            </div>
          </details>
        </div>
      </main>
    </div>

    <el-dialog v-model="renameVisible" title="重命名会话" width="420px">
      <el-input v-model="renameTitle" size="large" maxlength="40" show-word-limit />
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRename">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import {
  createChatSession,
  deleteChatSession,
  getChatHistory,
  getChatSessions,
  streamChatMessage,
  updateChatSession,
} from '../api/chat'
import { classifyIntent, listenVoice, speakText } from '../api/device'
import { getUsers } from '../api/users'
import { isPhotoIntent, resolvePhotoIntent } from '../utils/medicationIntent'
import { emitVoiceStop, getVoiceSessionBusy, isSessionExitPhrase, releaseVoiceSession, syncVoiceSessionBusy, VOICE_STOP_EVENT, waitForTtsIdle } from '../utils/voiceSession'

const router = useRouter()
const wakeSessionInFlight = inject('wakeSessionInFlight', ref(false))

const users = ref([])
const sessions = ref([])
const selectedUserId = ref(null)
const selectedSessionId = ref(null)
const messages = ref([])
const question = ref('')
const loading = ref(false)
const voiceLoading = ref(false)
const voicePhase = ref('idle')
const references = ref([])
const sessionKeyword = ref('')
const renameVisible = ref(false)
const renameTitle = ref('')
const renamingSessionId = ref(null)
const messageListRef = ref(null)
const voiceSessionActive = ref(false)
const voiceSessionRunning = ref(false)
let voiceSessionGen = 0
let streamAbortController = null
let routeLeaveHandled = false
const VOICE_INTRO_SPEECH = '请说您的问题。说退出可以结束并返回首页'
const VOICE_FOLLOWUP_SPEECH = '请继续说。说退出返回首页'
const VOICE_EXIT_SPEECH = '好的，已结束问诊，返回首页'

const bumpVoiceSessionGen = () => {
  voiceSessionGen += 1
  return voiceSessionGen
}

const isVoiceSessionLive = (gen) => gen === voiceSessionGen

const selectedUserName = computed(() => users.value.find((user) => user.id === selectedUserId.value)?.name || '未选择患者')
const currentSession = computed(() => sessions.value.find((session) => session.id === selectedSessionId.value))
const filteredSessions = computed(() => {
  const keyword = sessionKeyword.value.trim()
  if (!keyword) return sessions.value
  return sessions.value.filter((session) => session.title.includes(keyword))
})
const voiceBtnLabel = computed(() => {
  if (wakeSessionInFlight.value) return '唤醒占用中...'
  if (voiceSessionActive.value && !voiceLoading.value) return '连续对话中 · 说「退出」'
  if (voicePhase.value === 'preparing') return '请听提示...'
  if (voicePhase.value === 'listening') return '录音中...'
  if (voicePhase.value === 'thinking') return 'AI 思考中...'
  return '语音提问'
})
const voiceBtnDisabled = computed(
  () =>
    loading.value ||
    voiceLoading.value ||
    voiceSessionActive.value ||
    voiceSessionRunning.value ||
    (Boolean(wakeSessionInFlight.value) && !voiceSessionActive.value && !voiceLoading.value)
)
const statusHint = computed(() => {
  if (voicePhase.value === 'preparing') return '正在播放提示，请听完再开口...'
  if (voicePhase.value === 'listening') return '正在识别您说的话...'
  if (voicePhase.value === 'thinking') return 'AI 正在回答，文字和语音同步输出...'
  return 'AI 医生正在生成回复...'
})
const showLoadingBubble = computed(() => {
  if (!voiceLoading.value) return false
  return voicePhase.value === 'preparing' || voicePhase.value === 'listening'
})
const groupedSessions = computed(() => {
  const groups = [
    { title: '今天', items: [] },
    { title: '昨天', items: [] },
    { title: '更早', items: [] }
  ]
  filteredSessions.value.forEach((session) => {
    if (isToday(session.updated_at)) {
      groups[0].items.push(session)
    } else if (isYesterday(session.updated_at)) {
      groups[1].items.push(session)
    } else {
      groups[2].items.push(session)
    }
  })
  return groups
})

const formatTime = (value) => value ? new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
const formatDateTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'
const isToday = (value) => value && new Date(value).toDateString() === new Date().toDateString()
const isYesterday = (value) => {
  if (!value) return false
  const date = new Date(value)
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)
  return date.toDateString() === yesterday.toDateString()
}

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
    await loadSessions(true)
  }
}

const handleUserChange = async () => {
  selectedSessionId.value = null
  messages.value = []
  references.value = []
  await loadSessions(true)
}

const loadSessions = async (autoSelect = false) => {
  if (!selectedUserId.value) return
  try {
    const { data } = await getChatSessions(selectedUserId.value)
    sessions.value = data
    if (autoSelect && data.length) {
      await selectSession(data[0].id)
    }
  } catch (error) {
    ElMessage.error('会话列表加载失败，请确认后端服务已启动')
  }
}

const selectSession = async (sessionId) => {
  selectedSessionId.value = sessionId
  references.value = []
  try {
    const { data } = await getChatHistory(sessionId)
    messages.value = data
    scrollToBottom()
  } catch (error) {
    ElMessage.error('聊天记录加载失败')
  }
}

const newSession = async () => {
  if (!selectedUserId.value) {
    ElMessage.warning('请先选择患者')
    return
  }
  const { data } = await createChatSession({ user_id: selectedUserId.value })
  sessions.value.unshift(data)
  messages.value = []
  references.value = []
  selectedSessionId.value = data.id
}

const openRename = (session) => {
  renamingSessionId.value = session.id
  renameTitle.value = session.title
  renameVisible.value = true
}

const submitRename = async () => {
  if (!renameTitle.value.trim()) {
    ElMessage.warning('请输入会话标题')
    return
  }
  const { data } = await updateChatSession(renamingSessionId.value, { title: renameTitle.value })
  const index = sessions.value.findIndex((session) => session.id === data.id)
  if (index >= 0) sessions.value[index] = data
  renameVisible.value = false
  ElMessage.success('重命名成功')
}

const removeSession = async (sessionId) => {
  await ElMessageBox.confirm('删除后将同时删除该会话全部聊天记录，是否继续？', '确认删除', { type: 'warning' })
  await deleteChatSession(sessionId)
  sessions.value = sessions.value.filter((session) => session.id !== sessionId)
  if (selectedSessionId.value === sessionId) {
    selectedSessionId.value = sessions.value[0]?.id || null
    messages.value = []
    references.value = []
    if (selectedSessionId.value) await selectSession(selectedSessionId.value)
  }
  ElMessage.success('删除成功')
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
    loadSessions(false)
  } catch (error) {
    if (error?.name === 'AbortError') {
      return
    }
    throw error
  } finally {
    streamAbortController = null
  }
}

const sendMessage = async () => {
  const text = question.value.trim()
  if (!selectedUserId.value) {
    ElMessage.warning('请先选择患者')
    return
  }
  if (!selectedSessionId.value) {
    await newSession()
  }
  if (!text) {
    ElMessage.warning('请输入问题')
    return
  }

  const localId = Date.now()
  messages.value.push({ localId, role: 'user', content: text, created_at: new Date().toISOString() })
  question.value = ''
  scrollToBottom()

  if (await resolvePhotoIntent(text, classifyIntent)) {
    await switchToPhotoMedicine(text)
    return
  }

  loading.value = true

  try {
    await runStreamingChat(text, false)
  } catch (error) {
    ElMessage.error(error.message || 'AI医生回复失败')
  } finally {
    loading.value = false
    scrollToBottom()
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
  sessionStorage.setItem('photo_session_handoff', String(Date.now()))
  sessionStorage.setItem(
    'wake_photo_payload',
    JSON.stringify({
      user_id: selectedUserId.value,
      intent: 'photo',
      text: text || '请读取药盒包装上的药品名称，并说明用法用量和注意事项。',
      fast_handoff: true,
    }),
  )
  syncVoiceSessionBusy('photo')
  await router.push('/photo-medicine')
}

const runOneVoiceTurn = async () => {
  const gen = voiceSessionGen
  const { data: listenData } = await listenVoice(false, '')
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
            ElMessage.warning('没有听清，请再说一次，或说退出返回首页')
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
    await speakText('请说您的问题', true)
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
    await loadSessions(false)
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
      const { data } = await listenVoice(false, '')
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
      stopVoiceSession()
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
  if (wakeSessionInFlight.value) {
    ElMessage.info('正在等待唤醒词，请稍后再试')
    return
  }
  let payload = payloadFromEvent
  if (!payload) {
    const raw = sessionStorage.getItem('wake_chat_payload')
    if (!raw) return
    sessionStorage.removeItem('wake_chat_payload')
    try {
      payload = JSON.parse(raw)
    } catch {
      return
    }
  }
  try {
    await processWakePayload(payload)
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
  if (!routeLeaveHandled && !isDoctorHandoffActive()) {
    const handoff = sessionStorage.getItem('photo_session_handoff')
    const photoPayload = sessionStorage.getItem('wake_photo_payload')
    if (!handoff && !photoPayload) {
      releaseVoiceSession({ cancelWake: false })
    }
  }
})

watch([voiceSessionActive, voiceLoading], ([active, voiceBusy]) => {
  syncVoiceBusyFlag(active || voiceBusy)
})</script>

<style scoped>
.chat-page {
  height: 100%;
  min-height: 0;
}

.chat-page__head {
  margin-bottom: 6px;
}

.chat-page__head h1 {
  font-size: 22px;
}

.chat-page__head .el-select {
  width: 140px;
}

.chat-shell {
  display: grid;
  grid-template-columns: 188px minmax(0, 1fr);
  gap: 8px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.history-panel,
.chat-panel {
  min-height: 0;
  overflow: hidden;
}

.history-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
}

.panel-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.panel-top__info {
  min-width: 0;
}

.panel-top span,
.panel-top small {
  display: block;
}

.panel-top span {
  font-size: 16px;
  font-weight: 800;
  line-height: 1.2;
}

.panel-top small {
  color: var(--muted);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-top .el-button {
  min-height: 38px;
  padding: 0 10px;
  font-size: 15px;
  flex-shrink: 0;
}

.session-search {
  width: 100%;
}

.session-search :deep(.el-input__wrapper) {
  min-height: 38px;
}

.session-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.session-group-title {
  margin: 4px 0 4px 2px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}

.session-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px;
  align-items: center;
  width: 100%;
  margin-bottom: 6px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}

.session-item.active {
  border-color: #93d2ff;
  background: #f0f8ff;
}

.session-main {
  min-width: 0;
}

.session-main strong,
.session-main span {
  display: block;
}

.session-main strong {
  overflow: hidden;
  margin-bottom: 2px;
  color: var(--text);
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-main span {
  color: var(--muted);
  font-size: 12px;
}

.session-actions {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.session-actions .el-button {
  min-height: auto;
  padding: 0;
  font-size: 13px;
}

.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding: 0;
}

.chat-titlebar {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.96);
}

.chat-titlebar strong {
  overflow: hidden;
  font-size: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-titlebar span {
  flex-shrink: 0;
  color: var(--muted);
  font-size: 13px;
}

.chat-titlebar__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.session-pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: #e8f5ff;
  color: #1677ff;
  font-size: 12px;
  font-weight: 600;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 12px;
}

.welcome-card {
  padding: 14px 16px;
  border-radius: 12px;
  background: linear-gradient(135deg, #f4fbff, #ffffff);
}

.welcome-card h2 {
  margin: 0 0 6px;
  font-size: 20px;
}

.welcome-card p {
  margin: 0;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.5;
}

.message-row {
  display: flex;
  margin-bottom: 10px;
}

.message-row.user {
  justify-content: flex-end;
}

.message-row.assistant {
  justify-content: flex-start;
}

.bubble {
  max-width: 88%;
  padding: 10px 14px;
  border-radius: 14px;
  box-shadow: 0 4px 12px rgba(36, 107, 180, 0.06);
}

.message-row.user .bubble {
  color: #fff;
  background: linear-gradient(135deg, #1a8cff, #5fc4ff);
  border-bottom-right-radius: 4px;
}

.message-row.assistant .bubble {
  background: #fff;
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}

.bubble p {
  margin: 0 0 4px;
  line-height: 1.55;
  font-size: 17px;
}

.bubble time {
  display: block;
  opacity: 0.72;
  font-size: 12px;
  text-align: right;
}

.loading-bubble {
  color: var(--muted);
  font-size: 15px;
}

.reference-list {
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  max-height: 44px;
  overflow: hidden;
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  background: #f8fbff;
}

.reference-list span {
  color: var(--muted);
  font-size: 14px;
  flex-shrink: 0;
}

.reference-list .el-tag {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.input-bar {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 10px;
  border-top: 1px solid var(--border);
  background: #fff;
}

.voice-first .voice-ask-btn {
  width: 100%;
  min-height: 52px;
  font-size: 20px;
  font-weight: 800;
  border-radius: 12px;
}

.text-input-toggle {
  font-size: 14px;
  color: var(--muted);
}

.text-input-toggle summary {
  cursor: pointer;
  user-select: none;
  list-style: none;
}

.text-input-toggle summary::-webkit-details-marker {
  display: none;
}

.text-input-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 72px;
  gap: 8px;
  align-items: end;
  margin-top: 8px;
}

.text-input-row .el-button {
  min-height: 42px;
  padding: 0 8px;
  font-size: 15px;
}

.text-input-row :deep(.el-textarea__inner) {
  min-height: 42px !important;
}
</style>
