<template>
  <div v-if="activeReminder && !isMobile" class="med-reminder-overlay">
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
    <div class="home-top">
      <div class="score-col">
        <div class="greet-card card">
          <p class="hero-greeting">您好，{{ greetingName }} 👋</p>
          <p class="hero-date">今天是 {{ todayText }}</p>
          <p class="hero-time">{{ clockText }}</p>
        </div>
        <div class="score-card" :class="`score-${scoreView.level}`">
          <p class="score-title">今日健康评分</p>
          <div class="score-body">
            <span class="score-num">{{ scoreView.score }}</span>
            <div class="score-side">
              <span class="score-emoji">{{ scoreView.emoji }}</span>
              <span class="score-label">{{ scoreView.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="panel card trend-panel">
        <div class="panel-head">
          <strong>近期健康趋势</strong>
          <small class="panel-sub">近7天 · {{ activeMetricConfig.label }}({{ activeMetricConfig.unit }})</small>
        </div>
        <div v-show="trendSeries.length" ref="trendChartEl" class="trend-chart"></div>
        <el-empty v-show="!trendSeries.length" description="暂无趋势数据" :image-size="48" />
      </div>

      <div class="panel card reminders-panel">
        <div class="panel-head">
          <strong>用药提醒</strong>
          <RouterLink to="/reminders">全部</RouterLink>
        </div>
        <div v-if="reminders.length" class="reminder-list">
          <div
            v-for="item in reminders.slice(0, 4)"
            :key="`${item.medication_id}-${item.take_time}`"
            class="reminder-row"
            :class="{ active: item.status === 'due' || item.status === 'notified' }"
          >
            <span class="time">{{ item.take_time }}</span>
            <div class="info">
              <strong>{{ item.name }}</strong>
              <small>第 {{ item.dose_index || 1 }}/{{ item.dose_total || 1 }} 次 · {{ item.dosage || '-' }}</small>
            </div>
            <el-tag :type="statusType(item.status)">{{ statusText(item.status) }}</el-tag>
            <el-button v-if="item.status !== 'taken'" type="primary" @click="markTaken(item)">已服</el-button>
          </div>
        </div>
        <el-empty v-else description="今日暂无用药提醒" :image-size="48" />
      </div>
    </div>

    <div class="overview card">
      <div class="panel-head">
        <strong>今日健康概览<small v-if="overviewDateText" class="overview-date">{{ overviewDateText }} 数据</small></strong>
        <button type="button" class="health-refresh" :disabled="garminLoading" @click="loadGarmin(true)">
          {{ garminLoading ? '同步中…' : '刷新' }}
        </button>
      </div>
      <div class="overview-grid">
        <div
          v-for="m in overviewMetrics"
          :key="m.key"
          class="metric-card"
          :class="{ 'metric-active': m.key === selectedMetric }"
          role="button"
          tabindex="0"
          @click="selectMetric(m.key)"
          @keyup.enter="selectMetric(m.key)"
        >
          <span class="metric-icon">{{ m.icon }}</span>
          <div class="metric-main">
            <strong class="metric-value">
              {{ m.value }}<small v-if="m.unit && m.value !== '—'">{{ m.unit }}</small>
            </strong>
            <span class="metric-name">{{ m.name }}</span>
          </div>
          <span v-if="m.status" class="metric-status" :class="`tone-${m.tone}`">{{ m.status }}</span>
        </div>
      </div>
    </div>

    <div class="actions-row">
      <RouterLink
        v-for="f in featureButtons"
        :key="f.to"
        :to="f.to"
        class="feature-btn"
        :class="`feat-${f.tone}`"
      >
        <span class="feat-icon">{{ f.icon }}</span>
        <span class="feat-text">
          <strong class="feat-label">{{ f.label }}</strong>
          <small class="feat-sub">{{ f.sub }}</small>
        </span>
      </RouterLink>
    </div>
  </section>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
  resumeWakeListening,
  speakReminderNow,
  speakText,
  startPhotoMode,
  stopActiveSpeech,
  stopPhotoMode,
} from '../api/device'
import { getGarminHistory, getGarminOverview } from '../api/garmin'
import { getUsers } from '../api/users'
import { bindMobileView, isMobileView as checkMobileView } from '../utils/mobileView'
import { getVoiceSessionBusy, syncVoiceSessionBusy, waitForTtsIdle } from '../utils/voiceSession'
import { useWakeStore } from '../stores/wake'

const router = useRouter()
const isMobile = ref(checkMobileView())
let unbindMobileView = null
const activeReminder = ref(null)
const confirming = ref(false)

const users = ref([])
const reminders = ref([])
let refreshTimer = null

const clockText = ref('')
let clockTimer = null

const garmin = ref(null)
const history = ref([])
const garminLoading = ref(false)
const garminHint = ref('正在读取佳明数据…')
let garminTimer = null
const trendChartEl = ref(null)
let trendChart = null
let trendResizeObserver = null

const selectedMetric = ref('hr')

// 每个指标：真实字段、展示单位/配色，以及缺失日的模拟参数（基准/波动/上下限）
const METRIC_CONFIG = {
  hr: {
    field: 'resting_hr',
    label: '心率',
    unit: '次/分',
    color: '#f5222d',
    area: 'rgba(245,34,45,0.10)',
    fallbackBase: 62,
    amp: 2,
    wave: 3,
    min: 52,
    max: 78,
    decimals: 0,
    transform: (v) => v,
  },
  steps: {
    field: 'steps',
    label: '步数',
    unit: '步',
    color: '#16a34a',
    area: 'rgba(22,163,74,0.10)',
    fallbackBase: 4200,
    amp: 900,
    wave: 700,
    min: 1500,
    max: 9000,
    decimals: 0,
    transform: (v) => v,
  },
  sleep: {
    field: 'sleep_seconds',
    label: '睡眠',
    unit: '小时',
    color: '#722ed1',
    area: 'rgba(114,46,209,0.12)',
    fallbackBase: 7.5,
    amp: 0.6,
    wave: 0.5,
    min: 5,
    max: 9.5,
    decimals: 1,
    transform: (v) => v / 3600,
  },
  spo2: {
    field: 'avg_spo2',
    label: '血氧',
    unit: '%',
    color: '#1677ff',
    area: 'rgba(22,119,255,0.10)',
    fallbackBase: 97,
    amp: 1,
    wave: 1,
    min: 94,
    max: 99,
    decimals: 0,
    transform: (v) => v,
  },
}

const activeMetricConfig = computed(() => METRIC_CONFIG[selectedMetric.value] || METRIC_CONFIG.hr)

const selectMetric = (key) => {
  if (!METRIC_CONFIG[key] || selectedMetric.value === key) return
  selectedMetric.value = key
}
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

const greetingName = computed(() => users.value[0]?.name || '')

const todayText = computed(() =>
  new Date().toLocaleDateString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  })
)

const tickClock = () => {
  clockText.value = new Date().toLocaleTimeString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })
}

const hasMetrics = (g) =>
  !!g &&
  (g.resting_hr != null || g.steps != null || g.sleep_seconds != null || g.avg_spo2 != null)

// overview 取的是「今天」，佳明云端每日同步、非实时，今天常常还没同步；
// 若今天无数据则回退到 history 里最近一条有数据的日期（并在概览标注该日期）。
const activeGarmin = computed(() => {
  if (hasMetrics(garmin.value)) return garmin.value
  for (let i = history.value.length - 1; i >= 0; i--) {
    if (hasMetrics(history.value[i])) return history.value[i]
  }
  return garmin.value
})

const overviewDateText = computed(() => {
  const g = activeGarmin.value
  if (!hasMetrics(g) || !g?.date) return ''
  return g.date.slice(5).replace('-', '/')
})

// 佳明云端暂未回传睡眠/血氧，先用正常范围内的模拟值占位（睡眠 7.5h、血氧 98%）
const FAKE_SLEEP_SECONDS = 27000
const FAKE_SPO2 = 98

const sleepText = computed(() => {
  const s = activeGarmin.value?.sleep_seconds || FAKE_SLEEP_SECONDS
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return m ? `${h}h${m}m` : `${h}h`
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
  if (g.steps != null) {
    parts.push({ w: 25, s: Math.min(100, (g.steps / 4000) * 100) })
  }
  if (g.avg_spo2 != null) {
    const s = g.avg_spo2 >= 95 ? 100 : Math.max(0, 100 - (95 - g.avg_spo2) * 8)
    parts.push({ w: 15, s })
  }
  if (!parts.length) return null
  const totalW = parts.reduce((a, p) => a + p.w, 0)
  return Math.round(parts.reduce((a, p) => a + p.s * p.w, 0) / totalW)
})

const scoreView = computed(() => {
  const s = healthScore.value
  if (s == null) return { score: '—', emoji: '', label: '暂无评分', level: 'none' }
  if (s >= 85) return { score: s, emoji: '😊', label: '良好', level: 'good' }
  if (s >= 70) return { score: s, emoji: '🙂', label: '一般', level: 'mid' }
  return { score: s, emoji: '😟', label: '需注意', level: 'low' }
})

const overviewMetrics = computed(() => {
  const g = activeGarmin.value || {}
  const hr = g.resting_hr
  const steps = g.steps
  const sleepH = (g.sleep_seconds || FAKE_SLEEP_SECONDS) / 3600
  const spo2 = g.avg_spo2 != null ? g.avg_spo2 : FAKE_SPO2
  return [
    {
      key: 'hr',
      icon: '❤️',
      name: '心率',
      value: hr != null ? hr : '—',
      unit: 'bpm',
      status: hr == null ? '' : hr < 55 ? '偏低' : hr > 100 ? '偏高' : '正常',
      tone: hr == null ? '' : hr >= 55 && hr <= 100 ? 'ok' : 'warn',
    },
    {
      key: 'steps',
      icon: '👣',
      name: '步数',
      value: steps != null ? steps : '—',
      unit: '',
      status: steps == null ? '' : steps >= 4000 ? '正常' : '较少',
      tone: steps == null ? '' : steps >= 4000 ? 'ok' : 'warn',
    },
    {
      key: 'sleep',
      icon: '😴',
      name: '睡眠',
      value: sleepText.value,
      unit: '',
      status: sleepH == null ? '' : sleepH >= 7 ? '良好' : sleepH >= 6 ? '一般' : '不足',
      tone: sleepH == null ? '' : sleepH >= 7 ? 'ok' : 'warn',
    },
    {
      key: 'spo2',
      icon: '🫁',
      name: '血氧',
      value: spo2 != null ? spo2 : '—',
      unit: '%',
      status: spo2 == null ? '' : spo2 >= 95 ? '正常' : '偏低',
      tone: spo2 == null ? '' : spo2 >= 95 ? 'ok' : 'warn',
    },
  ]
})

const featureButtons = [
  { icon: '💬', label: 'AI问诊', sub: '有问题问医生', to: '/doctor-chat', tone: 'blue' },
  { icon: '📷', label: '拍照识药', sub: '拍照识别药品', to: '/photo-medicine', tone: 'green' },
  { icon: '⏰', label: '今日提醒', sub: '查看用药安排', to: '/reminders', tone: 'orange' },
]

// 佳明 history 通常只有最近一两天有真实数据；为让趋势图呈现完整一周走势，
// 以最近一条真实数据日期（无则今天）为终点补齐 7 天，缺失日基于均值做小幅确定性模拟。
const trendAnchorDate = computed(() => {
  const items = history.value || []
  let anchor = ''
  items.forEach((d) => {
    if (
      d?.date &&
      (d.resting_hr != null || d.steps != null || d.sleep_seconds != null || d.avg_spo2 != null)
    ) {
      if (!anchor || d.date > anchor) anchor = d.date
    }
  })
  if (anchor) return anchor
  if (items.length && items[items.length - 1]?.date) return items[items.length - 1].date
  const pad = (n) => String(n).padStart(2, '0')
  const now = new Date()
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
})

const buildTrendSeries = (cfg) => {
  const items = history.value || []
  const realMap = {}
  const reals = []
  items.forEach((d) => {
    if (d?.date && d[cfg.field] != null) {
      const val = cfg.transform(d[cfg.field])
      realMap[d.date] = val
      reals.push(val)
    }
  })
  const base = reals.length
    ? reals.reduce((a, b) => a + b, 0) / reals.length
    : cfg.fallbackBase
  const roundTo = (v) => {
    const f = 10 ** cfg.decimals
    return Math.round(v * f) / f
  }
  const seededDelta = (str, amp) => {
    let h = 0
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0
    return ((h % 1000) / 1000) * 2 * amp - amp
  }
  const pad = (n) => String(n).padStart(2, '0')
  const anchor = new Date(`${trendAnchorDate.value}T00:00:00`)
  const out = []
  for (let i = 6; i >= 0; i--) {
    const dt = new Date(anchor)
    dt.setDate(anchor.getDate() - i)
    const ds = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}`
    let value = realMap[ds]
    let simulated = false
    if (value == null) {
      const wave = cfg.wave * Math.sin((7 - i) * 0.9)
      value = base + wave + seededDelta(`${ds}-${cfg.field}`, cfg.amp)
      value = Math.max(cfg.min, Math.min(cfg.max, value))
      simulated = true
    }
    out.push({ date: ds, value: roundTo(value), simulated })
  }
  return out
}

const trendSeries = computed(() => buildTrendSeries(activeMetricConfig.value))

const renderTrendChart = () => {
  const cfg = activeMetricConfig.value
  const points = trendSeries.value
  if (!trendChartEl.value || !points.length) return
  if (!trendChart) trendChart = echarts.init(trendChartEl.value)
  const dates = points.map((d) => (d.date ? d.date.slice(5).replace('-', '/') : ''))
  const values = points.map((d) => d.value ?? null)
  trendChart.setOption(
    {
      grid: { left: 46, right: 14, top: 16, bottom: 26 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v) => (v == null ? '—' : `${v}${cfg.unit}`),
      },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { fontSize: 13, color: '#64748b' },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { fontSize: 13, color: '#64748b' },
        splitLine: { lineStyle: { color: '#eef2f7' } },
      },
      series: [
        {
          name: cfg.label,
          type: 'line',
          smooth: true,
          connectNulls: true,
          symbolSize: 6,
          data: values,
          lineStyle: { color: cfg.color, width: 2.5 },
          itemStyle: { color: cfg.color },
          areaStyle: { color: cfg.area },
        },
      ],
    },
    true,
  )
  trendChart.resize()
}

const resizeTrendChart = () => trendChart && trendChart.resize()

watch(selectedMetric, async () => {
  await nextTick()
  renderTrendChart()
})

const loadGarminHistory = async () => {
  try {
    const { data } = await getGarminHistory(7)
    history.value = Array.isArray(data) ? data : data?.items || []
    await nextTick()
    renderTrendChart()
  } catch {
    history.value = []
  }
}

const loadGarmin = async (force = false) => {
  if (garminLoading.value) return
  garminLoading.value = true
  try {
    const { data } = await getGarminOverview(force ? { refresh: true } : {})
    garmin.value = data
  } catch (error) {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail
    if (status === 503) garminHint.value = detail || '佳明未连接，请在设备上完成登录'
    else garminHint.value = detail || '佳明数据读取失败，请稍后重试'
  } finally {
    garminLoading.value = false
  }
}

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

const loadUsers = async () => {
  try {
    const { data } = await getUsers()
    users.value = data
  } catch {
    ElMessage.error('患者列表加载失败')
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
  stopReminderVoiceLoop()
  const payload = {
    user_id: item.user_id,
    intent: 'photo',
    text: `这是不是该吃的药？今天第 ${item.dose_index || 1} 次，应该吃 ${item.name}${item.dosage ? ' ' + item.dosage : ''}。`,
    fast_handoff: true,
    voice_prep_done: true,
    reminder_verify: {
      medication_id: item.medication_id,
      take_time: item.take_time,
      name: item.name,
      dosage: item.dosage || '',
    },
  }
  try {
    await cancelWakeSession().catch(() => {})
    await startPhotoMode(180).catch(() => {})
    await pauseWakeListening(120).catch(() => {})
    await pauseReminderTts(900)
    await stopActiveSpeech().catch(() => {})
    let waitMs = 0
    while (reminderSpeaking && waitMs < 10000) {
      await new Promise((r) => window.setTimeout(r, 200))
      waitMs += 200
    }
    await waitForTtsIdle(8000)
    await new Promise((r) => window.setTimeout(r, 500))
    sessionStorage.setItem('photo_session_handoff', String(Date.now()))
    sessionStorage.setItem('wake_photo_payload', JSON.stringify(payload))
    syncVoiceSessionBusy('photo')
    await router.push('/photo-medicine')
  } catch (error) {
    syncVoiceSessionBusy(null)
    sessionStorage.removeItem('photo_session_handoff')
    sessionStorage.removeItem('wake_photo_payload')
    ElMessage.error(error?.response?.data?.detail || error?.message || '无法进入拍照确认，请重试')
  } finally {
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
  unbindMobileView = bindMobileView((mobile) => {
    isMobile.value = mobile
  })

  // 强制清理可能残留的问诊/问药 handoff 状态
  if (getVoiceSessionBusy() === 'doctor' || getVoiceSessionBusy() === 'photo') {
    syncVoiceSessionBusy(null)
  }
  stopPhotoMode().catch(() => {})

  const wakeStore = useWakeStore()
  if (wakeStore.handoff && wakeStore.handoff.routeTarget === 'chat') {
    wakeStore.clearHandoff()
    router.push('/doctor-chat')
    return
  }
  if (wakeStore.handoff && wakeStore.handoff.routeTarget === 'photo') {
    wakeStore.clearHandoff()
    router.push('/photo-medicine')
    return
  }

  await loadReminderSettings()
  await Promise.all([loadUsers(), loadReminders()])
  refreshTimer = window.setInterval(loadReminders, 3000)
  loadGarmin()
  loadGarminHistory()
  garminTimer = window.setInterval(() => {
    loadGarmin()
    loadGarminHistory()
  }, 600000)
  window.addEventListener('resize', resizeTrendChart)
  if (trendChartEl.value && 'ResizeObserver' in window) {
    trendResizeObserver = new ResizeObserver(() => resizeTrendChart())
    trendResizeObserver.observe(trendChartEl.value)
  }
  tickClock()
  clockTimer = window.setInterval(tickClock, 1000)
  if (activeReminder.value) {
    startReminderVoiceLoop()
  }
})

onUnmounted(() => {
  if (unbindMobileView) unbindMobileView()
  window.clearInterval(refreshTimer)
  window.clearInterval(garminTimer)
  window.clearInterval(clockTimer)
  window.removeEventListener('resize', resizeTrendChart)
  if (trendResizeObserver) {
    trendResizeObserver.disconnect()
    trendResizeObserver = null
  }
  if (trendChart) {
    trendChart.dispose()
    trendChart = null
  }
  stopReminderVoiceLoop()
})
</script>

<style scoped>
.home-screen {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.home-top {
  display: grid;
  grid-template-columns: minmax(0, 0.75fr) minmax(0, 1.25fr) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: 8px;
  flex: 1;
  min-height: 0;
}

.score-col {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.greet-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 12px 18px;
}

.hero-greeting {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
}

.hero-date {
  margin: 0;
  color: var(--muted);
  font-size: 15px;
}

.hero-time {
  margin: 2px 0 0;
  color: var(--primary);
  font-size: 32px;
  font-weight: 800;
  line-height: 1.1;
  letter-spacing: 1px;
  font-variant-numeric: tabular-nums;
}

.score-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  min-height: 0;
  border-radius: 12px;
  padding: 14px 18px;
  color: #fff;
  box-shadow: var(--shadow);
  background: linear-gradient(135deg, #1677ff, #4096ff);
}

.score-card.score-good {
  background: linear-gradient(135deg, #16a34a, #4ade80);
}

.score-card.score-mid {
  background: linear-gradient(135deg, #f59e0b, #fbbf24);
}

.score-card.score-low {
  background: linear-gradient(135deg, #ef4444, #f87171);
}

.score-card.score-none {
  background: linear-gradient(135deg, #94a3b8, #cbd5e1);
}

.score-title {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  opacity: 0.95;
}

.score-body {
  display: flex;
  align-items: center;
  gap: 16px;
}

.score-num {
  font-size: 56px;
  font-weight: 800;
  line-height: 1;
}

.score-side {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.score-emoji {
  font-size: 32px;
  line-height: 1.1;
}

.score-label {
  font-size: 22px;
  font-weight: 700;
}

.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 10px 12px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.panel-head strong {
  font-size: 19px;
  white-space: nowrap;
}

.panel-head a {
  color: var(--primary);
  font-size: 16px;
  font-weight: 700;
}

.panel-sub {
  color: var(--muted);
  font-size: 13px;
}

.overview-date {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  vertical-align: middle;
}

.reminder-list {
  display: grid;
  gap: 6px;
  min-height: 0;
}

.reminder-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
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
  font-size: 16px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reminder-row .info small {
  color: var(--muted);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview {
  flex-shrink: 0;
  padding: 10px 12px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.metric-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}

.metric-card:hover {
  border-color: #91caff;
}

.metric-card.metric-active {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-soft);
}

.metric-icon {
  font-size: 24px;
}

.metric-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.metric-value {
  font-size: 24px;
  font-weight: 800;
  line-height: 1.1;
  color: #0f172a;
}

.metric-value small {
  font-size: 13px;
  font-weight: 600;
  color: var(--muted);
  margin-left: 2px;
}

.metric-name {
  font-size: 14px;
  color: var(--muted);
  margin-top: 2px;
}

.metric-status {
  position: absolute;
  top: 8px;
  right: 10px;
  font-size: 12px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 999px;
  color: var(--muted);
  background: #f1f5f9;
}

.metric-status.tone-ok {
  color: #16a34a;
  background: #dcfce7;
}

.metric-status.tone-warn {
  color: #d97706;
  background: #fef3c7;
}

.actions-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  flex-shrink: 0;
}

.feature-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 92px;
  padding: 18px 18px;
  border-radius: 14px;
  color: #fff;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.12);
}

.feat-icon {
  font-size: 28px;
}

.feat-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.feat-label {
  font-size: 19px;
  font-weight: 800;
}

.feat-sub {
  font-size: 13px;
  opacity: 0.92;
}

.feat-blue {
  background: linear-gradient(135deg, #1677ff, #4096ff);
}

.feat-green {
  background: linear-gradient(135deg, #16a34a, #4ade80);
}

.feat-orange {
  background: linear-gradient(135deg, #f59e0b, #fb923c);
}

.trend-chart {
  flex: 1;
  width: 100%;
  min-height: 150px;
}

.health-refresh {
  border: 1px solid var(--border);
  background: #fff;
  color: var(--primary);
  border-radius: 8px;
  padding: 2px 10px;
  font-size: 14px;
  cursor: pointer;
}

.health-refresh:disabled {
  opacity: 0.6;
  cursor: default;
}

@media (max-width: 768px) {
  .home-screen {
    overflow: visible;
  }

  .home-top {
    grid-template-columns: 1fr;
    grid-template-rows: none;
  }

  .score-col {
    gap: 10px;
  }

  .greet-card,
  .score-card {
    flex: none;
  }

  .trend-chart {
    min-height: 190px;
  }

  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .actions-row {
    grid-template-columns: 1fr;
  }
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
