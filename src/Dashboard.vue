<template>
  <div v-if="activeReminder" class="med-reminder-overlay">
    <div class="med-reminder-card">
      <p class="med-reminder-badge">用药提醒</p>
      <h1 class="med-reminder-dose">
        第 {{ activeReminder.dose_index || 1 }} 次 · 今天共 {{ activeReminder.dose_total || 1 }} 次
      </h1>
      <p class="med-reminder-time">{{ activeReminder.take_time }} 到点</p>
      <h2 class="med-reminder-drug">{{ activeReminder.name }}</h2>
      <p v-if="activeReminder.dosage" class="med-reminder-meta">{{ activeReminder.dosage }}</p>
      <div class="med-reminder-actions">
        <button type="button" class="med-reminder-btn-taken" :disabled="confirming" @click="confirmTaken">
          {{ confirming ? '确认中…' : '我已吃药' }}
        </button>
        <button type="button" class="med-reminder-btn-photo" :disabled="confirming" @click="goPhotoVerify">
          {{ confirming ? '准备拍照…' : '拍照确认' }}
        </button>
      </div>
      <p class="med-reminder-hint">不确定是哪个药？请点「拍照确认」拍照核对。</p>
    </div>
  </div>
  <section class="home-screen">
    <div class="home-stats card">
      <div v-for="item in stats" :key="item.label" class="stat-item">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
      <el-select
        v-model="selectedUserId"
        placeholder="选择患者"
        class="patient-select"
        @change="loadHealthProfile"
      >
        <el-option v-for="user in users" :key="user.id" :label="user.name" :value="user.id" />
      </el-select>
    </div>

    <div class="home-main">
      <div class="panel card reminders-panel">
        <div class="panel-head">
          <strong>今日用药</strong>
          <RouterLink to="/reminders">全部</RouterLink>
        </div>
        <div v-if="reminders.length" class="reminder-list">
          <div
            v-for="item in reminders.slice(0, 3)"
            :key="`${item.medication_id}-${item.take_time}`"
            class="reminder-row"
            :class="{ active: item.status === 'due' || item.status === 'notified' }"
          >
            <span class="time">{{ item.take_time }}</span>
            <div class="info">
              <strong>{{ item.name }}</strong>
              <small>
                第 {{ item.dose_index || 1 }}/{{ item.dose_total || 1 }} 次 · {{ item.dosage || '-' }}
              </small>
            </div>
            <el-tag :type="statusType(item.status)">{{ statusText(item.status) }}</el-tag>
            <el-button
              v-if="item.status !== 'taken'"
              type="primary"
              @click="markTaken(item)"
            >
              已服
            </el-button>
          </div>
        </div>
        <el-empty v-else description="暂无提醒，请先在药物页添加" :image-size="48" />
        <p class="home-tip">首页需先喊「豆包」唤醒，听到「我在，请说」后再说问题；问药/问诊中说「退出」会返回本页。</p>
      </div>
    </div>

    <div class="home-actions card">
      <RouterLink v-for="item in quickLinks" :key="item.to" :to="item.to" class="action-btn">
        {{ item.label }}
      </RouterLink>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ackReminder,
  cancelWakeSession,
  getReminderSettings,
  getTodayReminders,
  nudgeReminder,
  pauseReminderTts,
  pauseWakeListening,
  resumeReminderTts,
  speakReminderNow,
  speakText,
  stopActiveSpeech,
} from '../api/device'
import { getDashboardStats, getHealthProfileInsight } from '../api/dashboard'
import { getUsers } from '../api/users'
import { syncVoiceSessionBusy, waitForTtsIdle } from '../utils/voiceSession'

const router = useRouter()
const activeReminder = ref(null)
const confirming = ref(false)

const dashboardStats = ref({ userCount: 0, recordCount: 0, medicationCount: 0, reminderCount: 0 })
const users = ref([])
const selectedUserId = ref(null)
const profile = ref(null)
const reminders = ref([])
let refreshTimer = null
const reminderRepeatMs = ref(45000)
let lastReminderVoiceKey = ''
let reminderVoiceTimer = null
let reminderSpeaking = false

const reminderVoiceKey = (item) => `${item?.medication_id}:${item?.take_time}`

const buildReminderSpeech = (item) => {
  const dose = item.dose_index ? `，今天第 ${item.dose_index} 次` : ''
  const user = item.user_name ? `${item.user_name}，` : ''
  return `${user}该吃 ${item.name}${dose} 了。请点屏幕「我已吃药」确认；不确定请点「拍照确认」。`
}

const speakActiveReminder = async () => {
  if (!activeReminder.value || reminderSpeaking) return
  reminderSpeaking = true
  try {
    const { data } = await speakReminderNow()
    if (data?.ok) return
    if (data?.reason === 'too_soon' || data?.reason === 'paused') return
    await speakText(buildReminderSpeech(activeReminder.value), true)
  } catch {
    try {
      await speakText(buildReminderSpeech(activeReminder.value), true)
    } catch {
      /* 下一轮继续试 */
    }
  } finally {
    reminderSpeaking = false
  }
}

const stopReminderVoiceLoop = () => {
  if (reminderVoiceTimer) {
    window.clearInterval(reminderVoiceTimer)
    reminderVoiceTimer = null
  }
}

const startReminderVoiceLoop = () => {
  stopReminderVoiceLoop()
  if (!activeReminder.value) return
  void speakActiveReminder()
  reminderVoiceTimer = window.setInterval(() => {
    void speakActiveReminder()
  }, reminderRepeatMs.value)
}

const loadReminderSettings = async () => {
  try {
    const { data } = await getReminderSettings()
    reminderRepeatMs.value = Math.max(20000, (data.repeat_sec || 45) * 1000)
  } catch {
    reminderRepeatMs.value = 45000
  }
}

const restartVoiceNudgeTimer = () => {
  startReminderVoiceLoop()
}

watch(activeReminder, (item) => {
  if (!item) {
    lastReminderVoiceKey = ''
    stopReminderVoiceLoop()
    return
  }
  const key = reminderVoiceKey(item)
  if (key !== lastReminderVoiceKey) {
    lastReminderVoiceKey = key
    void resumeReminderTts()
  }
  startReminderVoiceLoop()
})

const stats = computed(() => [
  { label: '档案', value: dashboardStats.value.userCount },
  { label: '病例', value: dashboardStats.value.recordCount },
  { label: '药物', value: dashboardStats.value.medicationCount },
  { label: '提醒', value: dashboardStats.value.reminderCount },
])

const quickLinks = [
  { label: '问诊', to: '/doctor-chat' },
  { label: '拍照问药', to: '/photo-medicine' },
  { label: '档案', to: '/profiles' },
  { label: '药物', to: '/medications' },
  { label: '提醒', to: '/reminders' },
]

const statusText = (status) => {
  if (status === 'taken') return '已服'
  if (status === 'notified') return '已提醒'
  if (status === 'due') return '到点'
  return '待服'
}

const statusType = (status) => {
  if (status === 'taken') return 'success'
  if (status === 'notified' || status === 'due') return 'warning'
  return 'info'
}

const loadStats = async () => {
  try {
    const { data } = await getDashboardStats()
    dashboardStats.value = data
  } catch {
    ElMessage.error('统计数据加载失败')
  }
}

const loadUsers = async () => {
  try {
    const { data } = await getUsers()
    users.value = data
    if (data.length && !selectedUserId.value) {
      selectedUserId.value = data[0].id
      await loadHealthProfile()
    }
  } catch {
    ElMessage.error('患者列表加载失败')
  }
}

const loadHealthProfile = async () => {
  if (!selectedUserId.value) {
    profile.value = null
    return
  }
  try {
    const { data } = await getHealthProfileInsight(selectedUserId.value)
    profile.value = data
  } catch {
    profile.value = null
  }
}

const loadReminders = async () => {
  try {
    const { data } = await getTodayReminders()
    reminders.value = data
    activeReminder.value =
      data.find((item) => item.status === 'notified' || item.status === 'due') || null
  } catch {
    reminders.value = []
    activeReminder.value = null
  }
}

const confirmTaken = async () => {
  const item = activeReminder.value
  if (!item || confirming.value) return
  confirming.value = true
  try {
    await ackReminder(item.medication_id, item.take_time)
    ElMessage.success(`已记录：${item.name}`)
    await loadReminders()
  } catch {
    ElMessage.error('确认失败')
  } finally {
    confirming.value = false
  }
}

const goPhotoVerify = async () => {
  const item = activeReminder.value
  if (!item || confirming.value) return
  confirming.value = true
  const payload = {
    user_id: item.user_id,
    intent: 'photo',
    text: `这是不是该吃的药？今天第 ${item.dose_index || 1} 次，应该吃 ${item.name}${item.dosage ? ' ' + item.dosage : ''}。`,
    fast_handoff: true,
    voice_prep_done: false,
    reminder_verify: {
      medication_id: item.medication_id,
      take_time: item.take_time,
      name: item.name,
      dosage: item.dosage || '',
    },
  }
  sessionStorage.setItem('photo_session_handoff', String(Date.now()))
  sessionStorage.setItem('wake_photo_payload', JSON.stringify(payload))
  syncVoiceSessionBusy('photo')
  stopReminderVoiceLoop()
  try {
    await pauseReminderTts(900)
    await stopActiveSpeech().catch(() => {})
    await cancelWakeSession().catch(() => {})
    await pauseWakeListening(60).catch(() => {})
    let waitMs = 0
    while (reminderSpeaking && waitMs < 10000) {
      await new Promise((r) => window.setTimeout(r, 200))
      waitMs += 200
    }
    await waitForTtsIdle(8000)
    await new Promise((r) => window.setTimeout(r, 500))
    await router.push('/photo-medicine')
  } catch (error) {
    syncVoiceSessionBusy(null)
    sessionStorage.removeItem('photo_session_handoff')
    sessionStorage.removeItem('wake_photo_payload')
    ElMessage.error(error?.response?.data?.detail || error?.message || '无法进入拍照确认，请重试')
    confirming.value = false
  }
}

const markTaken = async (item) => {
  try {
    await ackReminder(item.medication_id, item.take_time)
    await loadReminders()
  } catch {
    ElMessage.error('标记失败')
  }
}

onMounted(async () => {
  await loadReminderSettings()
  await Promise.all([loadStats(), loadUsers(), loadReminders()])
  refreshTimer = window.setInterval(loadReminders, 3000)
  if (activeReminder.value) {
    startReminderVoiceLoop()
  }
})

onUnmounted(() => {
  window.clearInterval(refreshTimer)
  stopReminderVoiceLoop()
})
</script>

<style scoped>
.home-screen {
  display: grid;
  grid-template-rows: 54px minmax(0, 1fr) 54px;
  gap: 8px;
  height: 100%;
  min-height: 0;
}

.home-stats {
  display: grid;
  grid-template-columns: repeat(4, 72px) minmax(140px, 1fr);
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
}

.stat-item span,
.stat-item strong {
  display: block;
}

.stat-item span {
  color: var(--muted);
  font-size: 15px;
}

.stat-item strong {
  font-size: 22px;
  line-height: 1.1;
}

.patient-select {
  justify-self: end;
  width: min(160px, 100%);
}

.home-main {
  min-height: 0;
}

.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  padding: 10px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.panel-head strong {
  font-size: 20px;
  white-space: nowrap;
}

.panel-head a {
  color: var(--primary);
  font-size: 17px;
  font-weight: 700;
}

.reminder-list {
  display: grid;
  gap: 6px;
  min-height: 0;
  overflow: hidden;
}

.reminder-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
}

.reminder-row.active {
  border-color: #91caff;
  background: #f0f7ff;
}

.reminder-row .time {
  color: var(--primary);
  font-size: 18px;
  font-weight: 800;
}

.reminder-row .info strong {
  font-size: 17px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reminder-row .info small {
  color: var(--muted);
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.home-tip {
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 15px;
  line-height: 1.5;
}

.home-actions {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
  padding: 4px 6px;
  align-items: stretch;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 46px;
  padding: 4px 2px;
  border-radius: 10px;
  background: linear-gradient(180deg, #fff, #f3f8ff);
  color: var(--primary);
  font-size: 17px;
  font-weight: 800;
  white-space: nowrap;
  line-height: 1;
}

.med-reminder-overlay {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(8, 15, 30, 0.84);
}

.med-reminder-card {
  width: min(580px, 100%);
  padding: 32px 28px;
  border-radius: 22px;
  background: #fff;
  text-align: center;
  box-shadow: 0 28px 64px rgba(0, 0, 0, 0.35);
}

.med-reminder-badge {
  margin: 0 0 10px;
  font-size: 20px;
  font-weight: 700;
  color: #1677ff;
}

.med-reminder-dose {
  margin: 0 0 8px;
  font-size: 32px;
  color: #0f172a;
}

.med-reminder-time {
  margin: 0 0 18px;
  font-size: 24px;
  color: #64748b;
}

.med-reminder-drug {
  margin: 0 0 10px;
  font-size: 40px;
  color: #1677ff;
}

.med-reminder-meta {
  margin: 0 0 8px;
  font-size: 22px;
  color: #475569;
}

.med-reminder-actions {
  display: grid;
  gap: 16px;
  margin-top: 32px;
}

.med-reminder-btn-taken,
.med-reminder-btn-photo {
  width: 100%;
  min-height: 88px;
  border: none;
  border-radius: 20px;
  font-size: 30px;
  font-weight: 700;
  cursor: pointer;
}

.med-reminder-btn-taken {
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
}

.med-reminder-btn-photo {
  color: #1677ff;
  background: #e8f3ff;
  border: 3px solid #91caff;
  font-size: 26px;
}

.med-reminder-hint {
  margin: 20px 0 0;
  font-size: 17px;
  color: #64748b;
}
</style>
