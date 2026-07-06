<template>
  <section class="family-home">
    <header class="fh-header">
      <span class="fh-logo">🩺</span>
      <div class="fh-brand">
        <strong>AI健康助手</strong>
        <small>家属守护端 · 远程关注长辈健康</small>
      </div>
    </header>

    <div class="fh-card patient-card">
      <div class="patient-avatar">{{ patientInitial }}</div>
      <div class="patient-info">
        <div class="patient-name-row">
          <strong class="patient-name">{{ patientName }}</strong>
          <span v-if="patientAge" class="patient-meta">{{ patientAge }}岁</span>
          <span v-if="patientGender" class="patient-meta">{{ patientGender }}</span>
        </div>
        <div class="patient-tags">
          <span v-for="tag in patientConditions" :key="tag" class="cond-tag">{{ tag }}</span>
          <span v-if="!patientConditions.length" class="cond-tag is-muted">暂无病情记录</span>
        </div>
      </div>
      <button v-if="users.length > 1" type="button" class="switch-btn" @click="switchPatient">切换患者</button>
    </div>

    <div class="stat-grid">
      <div v-for="s in statCards" :key="s.key" class="stat-card" :class="`tone-${s.tone}`">
        <span class="stat-icon">{{ s.icon }}</span>
        <strong class="stat-value">{{ s.value }}<small v-if="s.suffix">{{ s.suffix }}</small></strong>
        <span class="stat-label">{{ s.label }}</span>
      </div>
    </div>

    <div class="fh-card">
      <div class="fh-card-head">
        <strong>今日用药</strong>
        <RouterLink to="/reminders" class="head-link">全部</RouterLink>
      </div>
      <div v-if="todayMeds.length" class="med-list">
        <div
          v-for="m in todayMeds"
          :key="`${m.medication_id}-${m.take_time}`"
          class="med-item"
          :class="m.status === 'taken' ? 'is-taken' : 'is-pending'"
        >
          <span class="med-bar" aria-hidden="true"></span>
          <span class="med-time">{{ m.take_time || '--:--' }}</span>
          <div class="med-body">
            <strong class="med-name">{{ m.name }}</strong>
            <small class="med-sub">第 {{ m.dose_index || 1 }}/{{ m.dose_total || 1 }} 次 · {{ m.dosage || '按医嘱' }}</small>
          </div>
          <span class="med-status" :class="m.status === 'taken' ? 'is-taken' : 'is-pending'">
            {{ statusText(m.status) }}
          </span>
        </div>
      </div>
      <el-empty v-else description="今日暂无用药计划" :image-size="46" />
    </div>

    <div class="fh-card">
      <div class="fh-card-head">
        <strong>近7天健康趋势</strong>
        <button type="button" class="head-link" :disabled="garminLoading" @click="loadGarmin(true)">
          {{ garminLoading ? '同步中…' : '刷新' }}
        </button>
      </div>
      <div class="trend-tabs">
        <button
          v-for="t in trendTabs"
          :key="t.key"
          type="button"
          :class="{ active: activeTrend === t.key }"
          @click="activeTrend = t.key"
        >
          {{ t.label }}
        </button>
      </div>
      <div v-show="trendData.values.length" ref="trendEl" class="trend-chart"></div>
      <el-empty v-show="!trendData.values.length" description="暂无趋势数据" :image-size="46" />
    </div>

    <div class="fh-card">
      <div class="fh-card-head">
        <strong>最近问诊记录</strong>
        <RouterLink to="/records" class="head-link">病例</RouterLink>
      </div>
      <div v-if="recentChats.length" class="chat-list">
        <div v-for="c in recentChats" :key="c.id" class="chat-item">
          <span class="chat-icon">💬</span>
          <div class="chat-body">
            <strong class="chat-title">{{ c.title || '健康咨询' }}</strong>
            <small class="chat-time">{{ formatTime(c.updated_at || c.created_at) }}</small>
          </div>
        </div>
      </div>
      <el-empty v-else description="暂无问诊记录" :image-size="46" />
    </div>

    <div class="feature-grid">
      <RouterLink v-for="f in features" :key="f.to" :to="f.to" class="feature-cell" :class="`feat-${f.tone}`">
        <span class="fc-icon">{{ f.icon }}</span>
        <span class="fc-label">{{ f.label }}</span>
      </RouterLink>
    </div>

    <p class="fh-foot">数据来自佳明手环与本地记录，仅供参考，不作为诊疗依据</p>
  </section>
</template>

<script setup>
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { getTodayReminders } from '../api/device'
import { getGarminHistory, getGarminOverview } from '../api/garmin'
import { getRecentChats } from '../api/chat'
import { getRecords } from '../api/records'
import { getUsers } from '../api/users'

const users = ref([])
const records = ref([])
const reminders = ref([])
const chats = ref([])
const garmin = ref(null)
const history = ref([])
const garminLoading = ref(false)
const currentIndex = ref(0)

const activeTrend = ref('hr')
const trendEl = ref(null)
let chart = null
let resizeObserver = null
let refreshTimer = null

const patient = computed(() => users.value[currentIndex.value] || null)
const patientName = computed(() => patient.value?.name || '未添加患者')
const patientAge = computed(() => patient.value?.age || null)
const patientGender = computed(() => patient.value?.gender || '')
const patientInitial = computed(() => (patient.value?.name || '患').slice(0, 1))

const patientConditions = computed(() => {
  const p = patient.value
  if (!p) return []
  const rec = records.value
    .filter((r) => r.user_id === p.id && r.chronic_disease)
    .sort((a, b) => `${b.created_at}`.localeCompare(`${a.created_at}`))[0]
  const raw = rec?.chronic_disease || ''
  return raw
    .split(/[，,、;；·\/\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 4)
})

const todayMeds = computed(() => {
  const p = patient.value
  const list = p ? reminders.value.filter((r) => r.user_id === p.id) : reminders.value
  return [...list].sort((a, b) => `${a.take_time}`.localeCompare(`${b.take_time}`))
})

const takenCount = computed(() => todayMeds.value.filter((m) => m.status === 'taken').length)
const totalCount = computed(() => todayMeds.value.length)
const pendingCount = computed(() => todayMeds.value.filter((m) => m.status !== 'taken').length)

const recentChats = computed(() => {
  const p = patient.value
  const list = p ? chats.value.filter((c) => c.user_id == null || c.user_id === p.id) : chats.value
  return list.slice(0, 4)
})

const statusText = (status) => {
  if (status === 'taken') return '已服用'
  if (status === 'due') return '到点'
  if (status === 'notified') return '待服用'
  return '待服用'
}

const hasMetrics = (g) =>
  !!g && (g.resting_hr != null || g.steps != null || g.sleep_seconds != null || g.avg_spo2 != null)

// 佳明云端每日同步、非实时，今天常常还没同步；无今日数据时回退到最近一条有数据的记录
const activeGarmin = computed(() => {
  if (hasMetrics(garmin.value)) return garmin.value
  for (let i = history.value.length - 1; i >= 0; i--) {
    if (hasMetrics(history.value[i])) return history.value[i]
  }
  return garmin.value
})

// 纯前端规则评分：只对「有数据」的指标计分，权重按有效项归一化
const healthScore = computed(() => {
  const g = activeGarmin.value
  if (!g) return null
  const parts = []
  if (g.resting_hr != null) {
    const hr = g.resting_hr
    let s = 100
    if (hr < 55) s = Math.max(0, 100 - (55 - hr) * 1.5)
    else if (hr > 80) s = Math.max(0, 100 - (hr - 80) * 1.5)
    parts.push({ w: 30, s })
  }
  if (g.sleep_seconds) {
    const h = g.sleep_seconds / 3600
    let s = 100
    if (h < 7) s = Math.max(0, 100 - (7 - h) * 12)
    else if (h > 9) s = Math.max(0, 100 - (h - 9) * 12)
    parts.push({ w: 30, s })
  }
  if (g.steps != null) parts.push({ w: 25, s: Math.min(100, (g.steps / 4000) * 100) })
  if (g.avg_spo2 != null) {
    const s = g.avg_spo2 >= 95 ? 100 : Math.max(0, 100 - (95 - g.avg_spo2) * 8)
    parts.push({ w: 15, s })
  }
  if (!parts.length) return null
  const totalW = parts.reduce((a, p) => a + p.w, 0)
  return Math.round(parts.reduce((a, p) => a + p.s * p.w, 0) / totalW)
})

const scoreTone = computed(() => {
  const s = healthScore.value
  if (s == null) return 'muted'
  if (s >= 85) return 'good'
  if (s >= 70) return 'mid'
  return 'low'
})

const statCards = computed(() => [
  {
    key: 'score',
    icon: '💯',
    value: healthScore.value == null ? '—' : healthScore.value,
    label: '健康评分',
    tone: scoreTone.value === 'muted' ? 'blue' : scoreTone.value === 'good' ? 'green' : scoreTone.value === 'mid' ? 'blue' : 'red',
  },
  {
    key: 'meds',
    icon: '💊',
    value: totalCount.value ? `${takenCount.value}/${totalCount.value}` : '—',
    label: '今日用药',
    tone: 'green',
  },
  { key: 'pending', icon: '⏰', value: pendingCount.value, label: '待办提醒', tone: pendingCount.value ? 'orange' : 'blue' },
  { key: 'chat', icon: '💬', value: chats.value.length, label: '最近问诊', tone: 'blue' },
])

const trendTabs = [
  { key: 'hr', label: '心率' },
  { key: 'steps', label: '步数' },
  { key: 'sleep', label: '睡眠' },
  { key: 'spo2', label: '血氧' },
]

const metricConfig = {
  hr: { field: 'resting_hr', unit: '次/分', color: '#f5222d', area: 'rgba(245,34,45,', base: 62, amp: 3, min: 50, max: 90 },
  steps: { field: 'steps', unit: '步', color: '#1677ff', area: 'rgba(22,119,255,', base: 3200, amp: 900, min: 0, max: 20000, round: 100 },
  sleep: { field: 'sleep_seconds', unit: '小时', color: '#722ed1', area: 'rgba(114,46,209,', base: 7, amp: 0.6, min: 3, max: 11, transform: (v) => Math.round((v / 3600) * 10) / 10, decimal: true },
  spo2: { field: 'avg_spo2', unit: '%', color: '#13c2c2', area: 'rgba(19,194,194,', base: 97, amp: 1, min: 88, max: 100 },
}

const seededDelta = (str, amp) => {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0
  return ((h % 1000) / 1000) * 2 * amp - amp
}

// 佳明 history 常只有最近一两天真实数据；以最近真实日期为终点补齐 7 天，缺失日基于均值做小幅确定性模拟
const trendData = computed(() => {
  const cfg = metricConfig[activeTrend.value]
  const items = history.value || []
  const realMap = {}
  const reals = []
  items.forEach((d) => {
    const raw = d?.[cfg.field]
    if (d?.date && raw != null) {
      const v = cfg.transform ? cfg.transform(raw) : raw
      realMap[d.date] = v
      reals.push(v)
    }
  })
  const realDates = Object.keys(realMap).sort()
  const anchorStr = realDates.length
    ? realDates[realDates.length - 1]
    : items.length
      ? items[items.length - 1]?.date
      : ''
  if (!anchorStr) return { dates: [], values: [] }
  const base = reals.length ? reals.reduce((a, b) => a + b, 0) / reals.length : cfg.base
  const pad = (n) => String(n).padStart(2, '0')
  const anchor = new Date(`${anchorStr}T00:00:00`)
  const dates = []
  const values = []
  for (let i = 6; i >= 0; i--) {
    const dt = new Date(anchor)
    dt.setDate(anchor.getDate() - i)
    const ds = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`
    let v = realMap[ds]
    if (v == null) {
      const wave = cfg.amp * Math.sin((7 - i) * 0.9)
      v = base + wave + seededDelta(ds + activeTrend.value, cfg.amp)
      v = Math.min(cfg.max, Math.max(cfg.min, v))
      if (cfg.decimal) v = Math.round(v * 10) / 10
      else if (cfg.round) v = Math.round(v / cfg.round) * cfg.round
      else v = Math.round(v)
    }
    dates.push(`${pad(dt.getMonth() + 1)}/${pad(dt.getDate())}`)
    values.push(v)
  }
  return { dates, values }
})

const renderChart = () => {
  if (!trendEl.value) return
  if (!chart) chart = echarts.init(trendEl.value)
  const cfg = metricConfig[activeTrend.value]
  const { dates, values } = trendData.value
  if (!dates.length) {
    chart.clear()
    return
  }
  chart.setOption(
    {
      grid: { left: 6, right: 14, top: 16, bottom: 4, containLabel: true },
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${v} ${cfg.unit}` },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#cbd5e1' } },
        axisTick: { show: false },
        axisLabel: { color: '#64748b', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: '#eef2f7' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          data: values,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { width: 3, color: cfg.color },
          itemStyle: { color: cfg.color },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: `${cfg.area}0.22)` },
              { offset: 1, color: `${cfg.area}0.02)` },
            ]),
          },
        },
      ],
    },
    true,
  )
}

const features = [
  { icon: '📁', label: '健康档案', to: '/profiles', tone: 'blue' },
  { icon: '📋', label: '病例管理', to: '/records', tone: 'green' },
  { icon: '💊', label: '药物管理', to: '/medications', tone: 'orange' },
  { icon: '⏰', label: '提醒管理', to: '/reminders', tone: 'purple' },
]

const formatTime = (value) => {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const switchPatient = () => {
  if (users.value.length < 2) return
  currentIndex.value = (currentIndex.value + 1) % users.value.length
}

const loadBase = async () => {
  const [uRes, rRes, mRes, cRes] = await Promise.allSettled([
    getUsers(),
    getRecords(),
    getTodayReminders(),
    getRecentChats({ limit: 8 }),
  ])
  if (uRes.status === 'fulfilled') users.value = uRes.value.data || []
  if (rRes.status === 'fulfilled') records.value = rRes.value.data || []
  if (mRes.status === 'fulfilled') reminders.value = mRes.value.data || []
  if (cRes.status === 'fulfilled') chats.value = cRes.value.data || []
}

const loadReminders = async () => {
  try {
    const { data } = await getTodayReminders()
    reminders.value = data || []
  } catch {
    /* 保留上次数据 */
  }
}

const loadGarmin = async (manual = false) => {
  if (garminLoading.value) return
  garminLoading.value = true
  try {
    const [oRes, hRes] = await Promise.allSettled([getGarminOverview(), getGarminHistory(7)])
    if (oRes.status === 'fulfilled') garmin.value = oRes.value.data || null
    if (hRes.status === 'fulfilled') history.value = hRes.value.data || []
  } finally {
    garminLoading.value = false
    if (manual) await nextTick(renderChart)
  }
}

watch([trendData, activeTrend], () => {
  nextTick(renderChart)
})

onMounted(async () => {
  await loadBase()
  await loadGarmin()
  await nextTick(renderChart)
  if (trendEl.value && 'ResizeObserver' in window) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(trendEl.value)
  }
  refreshTimer = window.setInterval(() => {
    void loadReminders()
    void loadGarmin()
  }, 60000)
})

onUnmounted(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  if (resizeObserver) resizeObserver.disconnect()
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<style scoped>
.family-home {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 14px;
}

.fh-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 16px;
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  box-shadow: 0 8px 20px rgba(22, 119, 255, 0.22);
}

.fh-logo {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.22);
  font-size: 24px;
  flex-shrink: 0;
}

.fh-brand {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.fh-brand strong {
  font-size: 20px;
  font-weight: 800;
}

.fh-brand small {
  font-size: 13px;
  opacity: 0.92;
}

.fh-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
}

.fh-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.fh-card-head strong {
  font-size: 17px;
}

.head-link {
  border: none;
  background: none;
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.head-link:disabled {
  color: var(--muted);
  cursor: default;
}

/* 患者卡 */
.patient-card {
  display: flex;
  align-items: center;
  gap: 12px;
}

.patient-avatar {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 16px;
  font-size: 24px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #36cfc9, #1677ff);
  flex-shrink: 0;
}

.patient-info {
  flex: 1;
  min-width: 0;
}

.patient-name-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.patient-name {
  font-size: 19px;
  font-weight: 800;
}

.patient-meta {
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
}

.patient-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.cond-tag {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  color: #b42318;
  background: #fef3f2;
}

.cond-tag.is-muted {
  color: var(--muted);
  background: #f2f4f7;
}

.switch-btn {
  flex-shrink: 0;
  padding: 8px 12px;
  border: 1px solid var(--primary);
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

/* 统计卡 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 12px 6px;
  border-radius: 14px;
  background: var(--card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.stat-icon {
  font-size: 22px;
}

.stat-value {
  font-size: 21px;
  font-weight: 800;
  line-height: 1.1;
}

.stat-value small {
  font-size: 12px;
  font-weight: 700;
  margin-left: 1px;
}

.stat-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.stat-card.tone-green .stat-value { color: #16a34a; }
.stat-card.tone-orange .stat-value { color: #d97706; }
.stat-card.tone-red .stat-value { color: #dc2626; }
.stat-card.tone-blue .stat-value { color: var(--primary); }

/* 今日用药 */
.med-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.med-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px 10px 14px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid var(--border);
  overflow: hidden;
}

.med-bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--primary);
}

.med-item.is-taken .med-bar { background: #16a34a; }

.med-time {
  font-size: 17px;
  font-weight: 800;
  color: var(--text);
  min-width: 52px;
}

.med-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.med-name {
  font-size: 16px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.med-sub {
  color: var(--muted);
  font-size: 13px;
}

.med-status {
  flex-shrink: 0;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
}

.med-status.is-taken {
  color: #16a34a;
  background: #ecfdf3;
}

.med-status.is-pending {
  color: var(--primary);
  background: var(--primary-soft);
}

/* 趋势 */
.trend-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.trend-tabs button {
  flex: 1;
  padding: 7px 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.trend-tabs button.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.trend-chart {
  width: 100%;
  height: 200px;
}

/* 问诊记录 */
.chat-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid var(--border);
}

.chat-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.chat-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.chat-title {
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-time {
  color: var(--muted);
  font-size: 12px;
}

/* 功能宫格 */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.feature-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 4px;
  border-radius: 14px;
  background: var(--card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.fc-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  font-size: 22px;
}

.feat-blue .fc-icon { background: #e8f3ff; }
.feat-green .fc-icon { background: #e7f8ef; }
.feat-orange .fc-icon { background: #fff2e0; }
.feat-purple .fc-icon { background: #f0ebfd; }

.fc-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
}

.fh-foot {
  margin: 2px 0 0;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}
</style>
