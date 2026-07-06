<template>
  <div v-if="activeReminder" class="reminder-overlay" role="dialog" aria-modal="true">
    <div class="reminder-card">
      <p class="reminder-badge">用药提醒</p>
      <h1 class="reminder-dose">
        第 {{ activeReminder.dose_index || 1 }} 次 · 今天共 {{ activeReminder.dose_total || 1 }} 次
      </h1>
      <p class="reminder-time">{{ activeReminder.take_time }} 到点</p>
      <h2 class="reminder-drug">{{ activeReminder.name }}</h2>
      <p v-if="activeReminder.dosage" class="reminder-meta">{{ activeReminder.dosage }}</p>
      <p v-if="activeReminder.user_name" class="reminder-user">{{ activeReminder.user_name }}</p>
      <p v-if="activeReminder.note" class="reminder-note">{{ activeReminder.note }}</p>

      <div class="reminder-actions">
        <button
          class="reminder-btn-taken"
          type="button"
          :disabled="confirming"
          @click="confirmTaken"
        >
          {{ confirming ? '确认中…' : '我已吃药' }}
        </button>
        <button
          class="reminder-btn-photo"
          type="button"
          :disabled="confirming"
          @click="goPhotoVerify"
        >
          拍照确认
        </button>
      </div>
      <p class="reminder-hint">不确定是哪个药？请点「拍照确认」，拿药盒拍照让 AI 帮您核对。</p>
    </div>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ackReminder, getPendingReminders, getTodayReminders } from '../api/device'

const router = useRouter()
const activeReminder = ref(null)
const confirming = ref(false)
let pollTimer = null

const pickPending = (items) =>
  (items || [])
    .filter((item) => item.status === 'due' || item.status === 'notified')
    .sort((a, b) => {
      const rank = (s) => (s === 'notified' ? 0 : 1)
      const diff = rank(a.status) - rank(b.status)
      if (diff !== 0) return diff
      return `${a.take_time}`.localeCompare(`${b.take_time}`)
    })[0] || null

const refreshPending = async () => {
  try {
    const { data } = await getPendingReminders()
    if (Array.isArray(data)) {
      activeReminder.value = data[0] || pickPending(data)
      if (activeReminder.value) return
    }
  } catch {
    /* pending 接口不可用时降级 */
  }
  try {
    const { data } = await getTodayReminders()
    activeReminder.value = pickPending(data)
  } catch {
    /* 离线时静默 */
  }
}

const confirmTaken = async () => {
  const item = activeReminder.value
  if (!item || confirming.value) return
  confirming.value = true
  try {
    await ackReminder(item.medication_id, item.take_time)
    ElMessage.success(`已记录：${item.name} 第 ${item.dose_index || 1} 次`)
    await refreshPending()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '确认失败，请重试')
  } finally {
    confirming.value = false
  }
}

const goPhotoVerify = async () => {
  const item = activeReminder.value
  if (!item || confirming.value) return
  const verifyText = item.name
    ? `这是不是该吃的药？今天第 ${item.dose_index || 1} 次，应该吃 ${item.name}${item.dosage ? ' ' + item.dosage : ''}。`
    : '这是不是该吃的药？'
  sessionStorage.setItem('photo_session_handoff', String(Date.now()))
  sessionStorage.setItem(
    'wake_photo_payload',
    JSON.stringify({
      user_id: item.user_id,
      intent: 'photo',
      text: verifyText,
      fast_handoff: true,
      reminder_verify: {
        medication_id: item.medication_id,
        take_time: item.take_time,
        name: item.name,
        dosage: item.dosage || '',
      },
    }),
  )
  await router.push('/photo-medicine')
}

const onVisibility = () => {
  if (document.visibilityState === 'visible') {
    refreshPending()
  }
}

onMounted(() => {
  refreshPending()
  pollTimer = window.setInterval(refreshPending, 3000)
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('focus', refreshPending)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener('focus', refreshPending)
})
</script>

<style scoped>
.reminder-overlay {
  position: fixed;
  inset: 0;
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.78);
  pointer-events: auto;
}

.reminder-card {
  width: min(560px, 100%);
  max-height: calc(100vh - 40px);
  overflow: auto;
  padding: 28px 24px 24px;
  border-radius: 20px;
  background: #fff;
  box-shadow: 0 24px 60px rgba(22, 119, 255, 0.28);
  text-align: center;
}

.reminder-badge {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 700;
  color: #1677ff;
}

.reminder-dose {
  margin: 0 0 6px;
  font-size: 30px;
  line-height: 1.25;
  color: #0f172a;
}

.reminder-time {
  margin: 0 0 16px;
  font-size: 22px;
  color: #64748b;
}

.reminder-drug {
  margin: 0 0 8px;
  font-size: 36px;
  line-height: 1.2;
  color: #1677ff;
}

.reminder-meta,
.reminder-user,
.reminder-note {
  margin: 0 0 6px;
  font-size: 20px;
  color: #475569;
}

.reminder-actions {
  display: grid;
  gap: 14px;
  margin-top: 28px;
}

.reminder-btn-taken,
.reminder-btn-photo {
  width: 100%;
  min-height: 80px;
  border: none;
  border-radius: 18px;
  font-size: 28px;
  font-weight: 700;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.reminder-btn-taken:disabled,
.reminder-btn-photo:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.reminder-btn-taken {
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  box-shadow: 0 12px 28px rgba(22, 119, 255, 0.38);
}

.reminder-btn-photo {
  color: #1677ff;
  background: #e8f3ff;
  border: 2px solid #91caff;
  font-size: 24px;
}

.reminder-hint {
  margin: 18px 0 0;
  font-size: 16px;
  line-height: 1.5;
  color: #64748b;
}
</style>
