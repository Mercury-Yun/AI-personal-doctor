<template>
  <section class="compact-page reminder-page">
    <div class="compact-page__head">
      <div class="head-left">
        <button type="button" class="back-btn" aria-label="返回首页" @click="goHome">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div class="head-title">
          <h1>用药提醒</h1>
          <span class="head-sub">按时用药，守护健康</span>
        </div>
      </div>
    </div>

    <div class="reminder-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}<span v-if="tab.showCount"> ({{ tab.count }})</span>
      </button>
    </div>

    <div class="reminder-layout">
      <aside class="summary-card card">
        <h3>今日用药完成情况</h3>
        <div class="ring-wrap">
          <svg class="ring" viewBox="0 0 120 120" aria-hidden="true">
            <circle class="ring-bg" cx="60" cy="60" r="52" />
            <circle
              class="ring-fg"
              cx="60"
              cy="60"
              r="52"
              :stroke-dasharray="ringCircumference"
              :stroke-dashoffset="ringOffset"
              :style="{ stroke: ringColor }"
            />
            <text x="60" y="56" text-anchor="middle" class="ring-num">{{ takenCount }}/{{ totalCount }}</text>
            <text x="60" y="78" text-anchor="middle" class="ring-sub">已完成</text>
          </svg>
          <strong class="ring-pct" :style="{ color: ringColor }">{{ percent }}%</strong>
          <span class="ring-cap">今日用药完成率</span>
        </div>

        <button type="button" class="btn-photo-big" @click="goPhotoVerifyGeneric">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" /><circle cx="12" cy="13" r="4" />
          </svg>
          拍照核对药品
        </button>
      </aside>

      <div class="plan-panel card">
        <div class="plan-head">
          <h3>今日服药计划</h3>
          <span class="plan-count">共 {{ totalCount }} 次服药计划</span>
        </div>

        <div v-if="filteredMedications.length" class="med-cards">
          <div
            v-for="item in filteredMedications"
            :key="`${item.medication_id}-${item.take_time}`"
            class="med-card"
            :class="item.status === 'taken' ? 'is-taken' : 'is-pending'"
          >
            <span class="med-bar" aria-hidden="true"></span>

            <div class="med-time">
              <strong>{{ item.take_time || '--:--' }}</strong>
              <small>{{ timeMeta(item).icon }} {{ timeMeta(item).label }}</small>
            </div>

            <div class="med-main">
              <div class="med-name">{{ item.name }}</div>
              <div class="med-tags">
                <span class="tag-chip">{{ item.frequency || '按时服用' }}</span>
                <span class="med-dose">第 {{ item.dose_index || 1 }}/{{ item.dose_total || 1 }} 次 · {{ item.dosage || '按医嘱' }}</span>
              </div>
              <p v-if="item.note" class="med-desc">{{ item.note }}</p>
            </div>

            <div class="med-status">
              <div class="status-badge" :class="item.status === 'taken' ? 'is-taken' : 'is-pending'">
                <template v-if="item.status === 'taken'">
                  <span class="badge-line">✓ 已服用</span>
                  <small v-if="takenTimeText(item)">{{ takenTimeText(item) }} 确认</small>
                </template>
                <template v-else>
                  <span class="badge-line">待服用</span>
                  <small>{{ remainingText(item) }}</small>
                </template>
              </div>
              <div class="med-actions">
                <button type="button" class="btn-ghost primary" @click="goPhotoVerify(item)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" /><circle cx="12" cy="13" r="4" />
                  </svg>
                  拍照核对
                </button>
                <button type="button" class="btn-ghost" @click="openDetail(item)">详情</button>
              </div>
            </div>
          </div>
        </div>
        <el-empty v-else :description="emptyText" :image-size="56" />
      </div>
    </div>

    <p class="reminder-foot">请勿自行调整用药方案，如有疑问请咨询医生或药师</p>

    <el-dialog v-model="detailVisible" title="用药详情" width="min(520px, 92vw)">
      <div v-if="detailItem" class="detail-body">
        <div class="detail-row"><span>药品名称</span><strong>{{ detailItem.name }}</strong></div>
        <div class="detail-row"><span>服用时间</span><strong>{{ detailItem.take_time || '--:--' }}（第 {{ detailItem.dose_index || 1 }}/{{ detailItem.dose_total || 1 }} 次）</strong></div>
        <div class="detail-row"><span>用法用量</span><strong>{{ detailItem.dosage || '按医嘱' }}</strong></div>
        <div class="detail-row"><span>服用频次</span><strong>{{ detailItem.frequency || '—' }}</strong></div>
        <div class="detail-row"><span>当前状态</span><strong>{{ statusLabel(detailItem.status) }}</strong></div>
        <div v-if="detailItem.note" class="detail-note">{{ detailItem.note }}</div>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button v-if="detailItem && detailItem.status !== 'taken'" type="primary" @click="markTakenFromDetail">
          标记已服用
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { ElMessage, ElNotification } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ackReminder, getTodayReminders } from '../api/device'

const router = useRouter()
const goHome = () => router.push('/dashboard')

const reminders = ref([])
const now = ref(new Date())
const activeTab = ref('today')
const detailVisible = ref(false)
const detailItem = ref(null)
const notifiedKeys = new Set()
let timer = null

const takenCount = computed(() => reminders.value.filter((i) => i.status === 'taken').length)
const totalCount = computed(() => reminders.value.length)
const pendingCount = computed(() => reminders.value.filter((i) => i.status !== 'taken').length)
const percent = computed(() => (totalCount.value ? Math.round((takenCount.value / totalCount.value) * 100) : 0))

const ringCircumference = 2 * Math.PI * 52
const ringOffset = computed(() => ringCircumference * (1 - percent.value / 100))
const ringColor = computed(() => (percent.value >= 100 && totalCount.value ? '#16a34a' : '#1677ff'))

const tabs = computed(() => [
  { key: 'today', label: '今日提醒', showCount: true, count: totalCount.value },
  { key: 'pending', label: '待服药', showCount: true, count: pendingCount.value },
  { key: 'taken', label: '已服药', showCount: true, count: takenCount.value },
  { key: 'all', label: '全部记录', showCount: false, count: totalCount.value },
])

const filteredMedications = computed(() => {
  if (activeTab.value === 'pending') return reminders.value.filter((i) => i.status !== 'taken')
  if (activeTab.value === 'taken') return reminders.value.filter((i) => i.status === 'taken')
  return reminders.value
})

const emptyText = computed(() => {
  if (activeTab.value === 'pending') return '暂无待服药物'
  if (activeTab.value === 'taken') return '今日还没有已服记录'
  return '暂无提醒，请先在药物管理中添加服用时间'
})

const nextPending = computed(
  () =>
    reminders.value
      .filter((i) => i.status !== 'taken')
      .sort((a, b) => `${a.take_time}`.localeCompare(`${b.take_time}`))[0] || null,
)

const statusLabel = (status) => {
  if (status === 'taken') return '已服用'
  if (status === 'notified') return '已提醒'
  if (status === 'due') return '到点未服'
  return '待服用'
}

const timeMeta = (item) => {
  const h = parseInt(`${item.take_time || '0'}`.split(':')[0], 10) || 0
  if (h < 5) return { icon: '🌙', label: '凌晨' }
  if (h < 11) return { icon: '☀️', label: '早上' }
  if (h < 14) return { icon: '☀️', label: '中午' }
  if (h < 18) return { icon: '🌤️', label: '下午' }
  return { icon: '🌙', label: '晚上' }
}

const remainingText = (item) => {
  if (!item.take_time) return ''
  const [h, m] = `${item.take_time}`.split(':').map((v) => parseInt(v, 10) || 0)
  const target = new Date(now.value)
  target.setHours(h, m, 0, 0)
  const diff = target.getTime() - now.value.getTime()
  if (diff <= 0) return '已到服药时间'
  const mins = Math.floor(diff / 60000)
  const hh = Math.floor(mins / 60)
  const mm = mins % 60
  return hh > 0 ? `还有 ${hh}小时${mm}分` : `还有 ${mm}分`
}

const takenTimeText = (item) => {
  if (!item.taken_at) return ''
  const d = new Date(item.taken_at)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const openDetail = (item) => {
  detailItem.value = item
  detailVisible.value = true
}

const notifyDueItems = () => {
  reminders.value.forEach((item) => {
    const key = `${item.medication_id}-${item.take_time}-${item.status}`
    if ((item.status === 'due' || item.status === 'notified') && !notifiedKeys.has(key)) {
      notifiedKeys.add(key)
      ElNotification({
        title: '请按时服用药物',
        message: `${item.user_name ? `${item.user_name} · ` : ''}第 ${item.dose_index || 1}/${item.dose_total || 1} 次 · ${item.name}`,
        type: 'warning',
        duration: 5000,
      })
    }
  })
}

const loadReminders = async () => {
  try {
    const { data } = await getTodayReminders()
    reminders.value = data
    notifyDueItems()
  } catch {
    ElMessage.error('用药提醒加载失败')
  }
}

const markTaken = async (item) => {
  try {
    await ackReminder(item.medication_id, item.take_time)
    ElMessage.success(`${item.name} 已标记`)
    await loadReminders()
  } catch {
    ElMessage.error('标记失败')
  }
}

const markTakenFromDetail = async () => {
  if (!detailItem.value) return
  await markTaken(detailItem.value)
  detailVisible.value = false
}

const goPhotoVerify = async (item) => {
  if (!item) return
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

const goPhotoVerifyGeneric = () => {
  if (nextPending.value) return goPhotoVerify(nextPending.value)
  return router.push('/photo-medicine')
}

onMounted(async () => {
  await loadReminders()
  timer = window.setInterval(async () => {
    now.value = new Date()
    await loadReminders()
  }, 30000)
})

onUnmounted(() => {
  window.clearInterval(timer)
})
</script>

<style scoped>
.reminder-page {
  gap: 0;
}

.head-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.head-sub {
  color: var(--muted);
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
}

.reminder-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 4px 0 10px;
}

.reminder-tabs button {
  padding: 8px 18px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--muted);
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.reminder-tabs button.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.reminder-layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 12px;
}

/* 左侧：今日完成情况 */
.summary-card {
  padding: 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
}

.summary-card h3 {
  margin: 0;
  font-size: 18px;
  color: var(--primary);
}

.ring-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.ring {
  width: 150px;
  height: 150px;
}

.ring-bg {
  fill: none;
  stroke: #e6eef8;
  stroke-width: 11;
}

.ring-fg {
  fill: none;
  stroke-width: 11;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 60px 60px;
  transition: stroke-dashoffset 0.5s ease, stroke 0.3s ease;
}

.ring-num {
  font-size: 30px;
  font-weight: 800;
  fill: var(--text);
}

.ring-sub {
  font-size: 14px;
  fill: var(--muted);
}

.ring-pct {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 800;
}

.ring-cap {
  color: var(--muted);
  font-size: 14px;
}

.btn-photo-big {
  margin-top: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  color: #fff;
  font-size: 18px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(22, 119, 255, 0.28);
}

.btn-photo-big svg {
  width: 22px;
  height: 22px;
}

.btn-photo-big:active {
  transform: scale(0.98);
}

/* 右侧：今日服药计划 */
.plan-panel {
  padding: 16px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.plan-head h3 {
  margin: 0;
  font-size: 19px;
}

.plan-count {
  color: var(--muted);
  font-size: 14px;
}

.med-cards {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.med-card {
  position: relative;
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 16px 16px 16px 22px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: #fff;
}

.med-card.is-taken {
  background: #f6fef9;
  border-color: #cdeede;
}

.med-bar {
  position: absolute;
  left: 8px;
  top: 12px;
  bottom: 12px;
  width: 5px;
  border-radius: 999px;
  background: #f59e0b;
}

.med-card.is-taken .med-bar {
  background: #22c55e;
}

.med-time strong {
  display: block;
  font-size: 26px;
  font-weight: 800;
  color: var(--text);
  line-height: 1.1;
}

.med-time small {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 14px;
}

.med-main {
  min-width: 0;
}

.med-name {
  font-size: 21px;
  font-weight: 800;
  color: var(--text);
}

.med-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 6px 0;
}

.tag-chip {
  padding: 3px 10px;
  border-radius: 8px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
}

.med-dose {
  color: var(--muted);
  font-size: 14px;
}

.med-desc {
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 15px;
}

.med-status {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  min-width: 148px;
}

.status-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 18px;
  border-radius: 12px;
  font-weight: 800;
  font-size: 16px;
  white-space: nowrap;
}

.status-badge.is-taken {
  background: #dcfce7;
  color: #16a34a;
}

.status-badge.is-pending {
  background: #fff4e2;
  color: #ea8a0c;
}

.status-badge small {
  font-size: 13px;
  font-weight: 600;
}

.med-actions {
  display: flex;
  gap: 8px;
}

.btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.btn-ghost svg {
  width: 16px;
  height: 16px;
}

.btn-ghost:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.btn-ghost.primary {
  color: var(--primary);
  border-color: #bcdcff;
}

.reminder-foot {
  margin: 10px 0 2px;
  text-align: center;
  color: var(--muted);
  font-size: 14px;
}

.detail-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 16px;
}

.detail-row span {
  color: var(--muted);
}

.detail-note {
  margin-top: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--text);
  font-size: 15px;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .reminder-layout {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .summary-card {
    overflow: visible;
  }

  .med-cards {
    overflow: visible;
  }

  .med-card {
    grid-template-columns: 72px minmax(0, 1fr);
    row-gap: 10px;
  }

  .med-status {
    grid-column: 1 / -1;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    min-width: 0;
  }
}
</style>
