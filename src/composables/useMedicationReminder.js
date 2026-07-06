import { ElMessage } from 'element-plus'
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ackReminder, getPendingReminders, getTodayReminders } from '../api/device'

export function useMedicationReminder() {
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
      if (Array.isArray(data) && data.length) {
        activeReminder.value = data[0]
        return
      }
    } catch {
      /* fallback */
    }
    try {
      const { data } = await getTodayReminders()
      activeReminder.value = pickPending(data)
    } catch {
      /* ignore */
    }
  }

  const confirmTaken = async () => {
    const item = activeReminder.value
    if (!item || confirming.value) return
    confirming.value = true
    try {
      await ackReminder(item.medication_id, item.take_time)
      ElMessage.success(`已记录：${item.name}`)
      await refreshPending()
    } catch (error) {
      ElMessage.error(error?.response?.data?.detail || '确认失败')
    } finally {
      confirming.value = false
    }
  }

  const goPhotoVerify = async () => {
    const item = activeReminder.value
    if (!item || confirming.value) return
    sessionStorage.setItem('photo_session_handoff', String(Date.now()))
    sessionStorage.setItem(
      'wake_photo_payload',
      JSON.stringify({
        user_id: item.user_id,
        intent: 'photo',
        text: `这是不是该吃的药？今天第 ${item.dose_index || 1} 次，应该吃 ${item.name}${item.dosage ? ' ' + item.dosage : ''}。`,
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

  const startPolling = () => {
    refreshPending()
    pollTimer = window.setInterval(refreshPending, 2000)
    document.addEventListener('visibilitychange', refreshPending)
    window.addEventListener('focus', refreshPending)
  }

  const stopPolling = () => {
    if (pollTimer) window.clearInterval(pollTimer)
    pollTimer = null
    document.removeEventListener('visibilitychange', refreshPending)
    window.removeEventListener('focus', refreshPending)
  }

  onMounted(startPolling)
  onUnmounted(stopPolling)

  return { activeReminder, confirming, confirmTaken, goPhotoVerify, refreshPending }
}
