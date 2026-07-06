<template>
  <section class="family-profiles">
    <!-- 列表页 -->
    <template v-if="view === 'list'">
      <header class="fp-header">
        <button type="button" class="back-btn" aria-label="返回首页" @click="goFamily">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div class="fp-title">
          <h1>健康档案</h1>
          <span>管理家庭成员健康信息</span>
        </div>
        <button type="button" class="fp-add" @click="openCreate">＋ 新增患者</button>
      </header>

      <div class="search-bar">
        <span class="search-icon" aria-hidden="true">🔍</span>
        <input v-model.trim="keyword" type="search" placeholder="搜索家庭成员姓名" />
      </div>

      <div class="stat-grid">
        <div v-for="s in listStats" :key="s.key" class="stat-card" :class="`tone-${s.tone}`">
          <span class="stat-icon">{{ s.icon }}</span>
          <strong class="stat-value">{{ s.value }}<small v-if="s.suffix">{{ s.suffix }}</small></strong>
          <span class="stat-label">{{ s.label }}</span>
          <span class="stat-sub">{{ s.sub }}</span>
        </div>
      </div>

      <div class="fp-card">
        <div class="fp-card-head">
          <strong>家庭成员</strong>
          <span class="head-count">{{ filteredUsers.length }} 人</span>
        </div>
        <div v-if="filteredUsers.length" class="member-list">
          <button
            v-for="u in filteredUsers"
            :key="u.id"
            type="button"
            class="member-card"
            @click="openDetail(u.id)"
          >
            <div class="member-avatar">{{ initialOf(u) }}</div>
            <div class="member-info">
              <div class="member-name-row">
                <strong class="member-name">{{ u.name }}</strong>
                <span v-if="isSelf(u)" class="self-tag">本人</span>
              </div>
              <span class="member-sub">{{ subLineOf(u) }}</span>
              <span class="member-time">更新于 {{ formatDate(u.created_at) }}</span>
            </div>
            <span class="chevron" aria-hidden="true">›</span>
          </button>
        </div>
        <el-empty v-else :description="keyword ? '未找到匹配的成员' : '暂无健康档案'" :image-size="52" />
      </div>

      <button type="button" class="add-member-card" @click="openCreate">
        <span class="am-icon">＋</span>
        <span class="am-text">添加新成员</span>
      </button>

      <div class="tip-card">
        <span class="tip-icon">💡</span>
        <div class="tip-body">
          <strong>使用提示</strong>
          <p>点击成员卡片可查看完整档案；部分健康指标为示例数据，接入设备后将自动更新。</p>
        </div>
      </div>
    </template>

    <!-- 详情页 -->
    <template v-else-if="current">
      <header class="fp-header">
        <button type="button" class="back-btn" aria-label="返回列表" @click="backToList">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div class="fp-title">
          <h1>健康档案详情</h1>
        </div>
        <button type="button" class="fp-add" @click="openEdit(current)">编辑</button>
      </header>

      <div class="detail-hero">
        <div class="hero-avatar">{{ initialOf(current) }}</div>
        <div class="hero-info">
          <div class="hero-name-row">
            <strong class="hero-name">{{ current.name }}</strong>
            <span v-if="isSelf(current)" class="self-tag light">本人</span>
          </div>
          <span class="hero-meta">{{ heroMeta }}</span>
          <div class="hero-tags">
            <span v-for="t in currentConditions" :key="t" class="cond-tag">{{ t }}</span>
            <span v-if="!currentConditions.length" class="cond-tag is-muted">暂无慢性病</span>
          </div>
        </div>
        <span class="hero-badge">健康状况 · 良好</span>
      </div>

      <div class="metric-grid">
        <div v-for="m in metricCards" :key="m.key" class="metric-card" :class="`tone-${m.tone}`">
          <span class="metric-icon">{{ m.icon }}</span>
          <strong class="metric-value">{{ m.value }}<small>{{ m.unit }}</small></strong>
          <span class="metric-label">{{ m.label }}</span>
        </div>
      </div>

      <div class="detail-tabs">
        <button
          v-for="t in detailTabs"
          :key="t.key"
          type="button"
          :class="{ active: activeTab === t.key }"
          @click="activeTab = t.key"
        >
          {{ t.label }}
        </button>
      </div>

      <div class="fp-card detail-panel">
        <div class="info-list">
          <div v-for="row in panelRows" :key="row.label" class="info-row">
            <span class="info-label">{{ row.label }}</span>
            <span class="info-value" :class="{ 'is-sample': row.sample }">{{ row.value }}</span>
          </div>
        </div>
      </div>

      <p class="sample-note">血压、血糖、体温为示例数据，接入设备后自动更新</p>

      <div class="detail-actions">
        <button type="button" class="act-btn edit" @click="openEdit(current)">编辑信息</button>
        <button type="button" class="act-btn del" @click="removeCurrent">删除档案</button>
      </div>
    </template>

    <!-- 新增 / 编辑表单 -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="92%" top="6vh" class="fp-dialog">
      <el-form :model="form" label-position="top" size="large">
        <el-form-item label="姓名"><el-input v-model="form.name" placeholder="请输入姓名" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="年龄"><el-input-number v-model="form.age" :min="0" :max="130" controls-position="right" /></el-form-item>
          <el-form-item label="性别">
            <el-select v-model="form.gender" placeholder="选择">
              <el-option label="男" value="男" />
              <el-option label="女" value="女" />
            </el-select>
          </el-form-item>
          <el-form-item label="身高(cm)"><el-input-number v-model="form.height" :min="0" :max="260" controls-position="right" /></el-form-item>
          <el-form-item label="体重(kg)"><el-input-number v-model="form.weight" :min="0" :max="400" controls-position="right" /></el-form-item>
        </div>
        <el-form-item label="血型">
          <el-select v-model="form.blood_type" placeholder="选择或输入血型" filterable allow-create default-first-option clearable>
            <el-option v-for="bt in BLOOD_TYPES" :key="bt" :label="bt" :value="bt" />
          </el-select>
        </el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.phone" placeholder="请输入联系电话" /></el-form-item>
        <el-form-item label="紧急联系人"><el-input v-model="form.emergency_contact" placeholder="紧急联系人姓名" /></el-form-item>
        <el-form-item label="紧急联系人电话"><el-input v-model="form.emergency_phone" placeholder="紧急联系人电话" /></el-form-item>
        <el-form-item label="过敏史"><el-input v-model="form.allergy" type="textarea" :rows="2" placeholder="如无可留空" /></el-form-item>
        <el-form-item label="慢性疾病"><el-input v-model="form.chronic_diseases" type="textarea" :rows="2" placeholder="如高血压、糖尿病，多个用顿号分隔；如无可留空" /></el-form-item>
      </el-form>
      <template #footer>
        <button type="button" class="dlg-btn ghost" @click="dialogVisible = false">取消</button>
        <button type="button" class="dlg-btn primary" @click="submitForm">保存</button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createUser, deleteUser, getUsers, updateUser } from '../api/users'
import { getGarminHistory, getGarminOverview } from '../api/garmin'

const router = useRouter()

const users = ref([])
const garmin = ref(null)
const history = ref([])

const view = ref('list')
const activeId = ref(null)
const activeTab = ref('basic')
const keyword = ref('')

const dialogVisible = ref(false)
const dialogMode = ref('create')
const editingId = ref(null)

const NONE_CONDITION = new Set(['无', '暂无', '无病史', '无慢性病', '无慢性疾病', '无特殊', '否认', '健康', '正常', '-', 'none'])

const initialOf = (u) => (u?.name || '患').slice(0, 1)
const isSelf = (u) => !!u && users.value.length > 0 && u.id === users.value[0].id

const conditionsOf = (userId) => {
  const u = users.value.find((x) => x.id === userId)
  const raw = u?.chronic_diseases || ''
  return raw
    .split(/[，,、;；·\/\s]+/)
    .map((s) => s.trim())
    .filter((s) => s && !NONE_CONDITION.has(s))
    .slice(0, 4)
}

const subLineOf = (u) => {
  const parts = []
  if (u.age != null) parts.push(`${u.age}岁`)
  if (u.gender) parts.push(u.gender)
  const cond = conditionsOf(u.id)
  parts.push(cond.length ? cond.join('、') : '无慢性病')
  return parts.join(' · ')
}

const filteredUsers = computed(() => {
  const kw = keyword.value.trim()
  if (!kw) return users.value
  return users.value.filter((u) => (u.name || '').includes(kw))
})

const formatDate = (value) => {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  const now = new Date()
  const same = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  if (same) return '今天'
  return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())}`
}

// ---- 列表统计 ----
const REQUIRED_FIELDS = ['name', 'age', 'gender', 'phone', 'height', 'weight']
const completeCount = computed(() =>
  users.value.filter((u) => REQUIRED_FIELDS.every((f) => u[f] != null && `${u[f]}`.trim() !== '')).length,
)
const completePercent = computed(() => (users.value.length ? Math.round((completeCount.value / users.value.length) * 100) : 0))
const warningCount = computed(() => users.value.filter((u) => conditionsOf(u.id).length > 0).length)
const latestUpdate = computed(() => {
  const times = users.value.map((u) => u.created_at).filter(Boolean).sort()
  return times.length ? formatDate(times[times.length - 1]) : '—'
})

const listStats = computed(() => [
  { key: 'members', icon: '👨‍👩‍👧', value: users.value.length, suffix: '人', label: '家庭成员', sub: '已建立档案', tone: 'blue' },
  { key: 'complete', icon: '✅', value: completePercent.value, suffix: '%', label: '完善档案', sub: `${completeCount.value} 人完整`, tone: 'green' },
  { key: 'update', icon: '🕒', value: latestUpdate.value, label: '最近更新', sub: '最新档案', tone: 'purple' },
  {
    key: 'warning',
    icon: warningCount.value ? '⚠️' : '🛡️',
    value: warningCount.value,
    suffix: '人',
    label: '健康预警',
    sub: warningCount.value ? '需关注' : '状态正常',
    tone: warningCount.value ? 'orange' : 'blue',
  },
])

// ---- 详情 ----
const current = computed(() => users.value.find((u) => u.id === activeId.value) || null)
const currentConditions = computed(() => (current.value ? conditionsOf(current.value.id) : []))

// 佳明真实静息心率（今日无数据回退最近一条），否则给示例值
const restingHr = computed(() => {
  const g = garmin.value
  if (g && g.resting_hr != null) return g.resting_hr
  const items = Array.isArray(history.value) ? history.value : []
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i]?.resting_hr != null) return items[i].resting_hr
  }
  return null
})

// 血型可选项（用户也可自定义输入）
const BLOOD_TYPES = ['A 型', 'B 型', 'O 型', 'AB 型']

const heroMeta = computed(() => {
  const u = current.value
  if (!u) return ''
  const parts = []
  if (u.age != null) parts.push(`${u.age}岁`)
  if (u.gender) parts.push(u.gender)
  return parts.join(' · ')
})

const metricCards = computed(() => [
  { key: 'bp', icon: '🩺', label: '血压', value: '120/80', unit: ' mmHg', tone: 'red' },
  { key: 'glucose', icon: '🩸', label: '血糖', value: '5.6', unit: ' mmol/L', tone: 'orange' },
  { key: 'hr', icon: '❤️', label: '心率', value: restingHr.value == null ? '61' : restingHr.value, unit: ' bpm', tone: 'pink' },
  { key: 'temp', icon: '🌡️', label: '体温', value: '36.5', unit: ' ℃', tone: 'blue' },
])

const detailTabs = [
  { key: 'basic', label: '基本信息' },
  { key: 'health', label: '健康信息' },
  { key: 'emergency', label: '紧急联系人' },
]

const panelRows = computed(() => {
  const u = current.value
  if (!u) return []
  const dash = (v) => (v == null || `${v}`.trim() === '' ? '未填写' : v)
  if (activeTab.value === 'basic') {
    return [
      { label: '姓名', value: dash(u.name) },
      { label: '性别', value: dash(u.gender) },
      { label: '年龄', value: u.age != null ? `${u.age} 岁` : '未填写' },
      { label: '身高', value: u.height != null ? `${u.height} cm` : '未填写' },
      { label: '体重', value: u.weight != null ? `${u.weight} kg` : '未填写' },
      { label: '联系电话', value: dash(u.phone) },
    ]
  }
  if (activeTab.value === 'health') {
    const cond = conditionsOf(u.id)
    return [
      { label: '血型', value: u.blood_type && u.blood_type.trim() ? u.blood_type : '未填写' },
      { label: '过敏史', value: u.allergy && u.allergy.trim() ? u.allergy : '无' },
      { label: '慢性疾病', value: cond.length ? cond.join('、') : '无' },
      { label: '健康状况', value: '良好' },
    ]
  }
  if (activeTab.value === 'emergency') {
    return [
      { label: '紧急联系人', value: dash(u.emergency_contact) },
      { label: '联系电话', value: dash(u.emergency_phone) },
    ]
  }
  return []
})

// ---- 交互 ----
const goFamily = () => router.push('/family')
const backToList = () => {
  view.value = 'list'
  activeId.value = null
}
const openDetail = (id) => {
  activeId.value = id
  activeTab.value = 'basic'
  view.value = 'detail'
}

const emptyForm = () => ({
  name: '', age: null, gender: '', height: null, weight: null, blood_type: '',
  phone: '', emergency_contact: '', emergency_phone: '', allergy: '', chronic_diseases: '', remark: '',
})
const form = reactive(emptyForm())
const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新增健康档案' : '编辑健康档案'))

const openCreate = () => {
  dialogMode.value = 'create'
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}
const openEdit = (u) => {
  dialogMode.value = 'edit'
  editingId.value = u.id
  Object.assign(form, emptyForm(), u)
  dialogVisible.value = true
}

const submitForm = async () => {
  if (!form.name || !form.name.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  try {
    if (dialogMode.value === 'create') {
      await createUser({ ...form })
    } else {
      await updateUser(editingId.value, { ...form })
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await loadBase()
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  }
}

const removeCurrent = async () => {
  const u = current.value
  if (!u) return
  try {
    await ElMessageBox.confirm(`删除后将同步删除「${u.name}」的关联病例，是否继续？`, '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteUser(u.id)
    ElMessage.success('已删除')
    backToList()
    await loadBase()
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

const loadBase = async () => {
  const [uRes] = await Promise.allSettled([getUsers()])
  if (uRes.status === 'fulfilled') users.value = uRes.value.data || []
}

const loadGarmin = async () => {
  const [oRes, hRes] = await Promise.allSettled([getGarminOverview(), getGarminHistory(7)])
  if (oRes.status === 'fulfilled') garmin.value = oRes.value.data || null
  if (hRes.status === 'fulfilled') {
    const d = hRes.value.data
    history.value = Array.isArray(d) ? d : d?.items || []
  }
}

onMounted(async () => {
  await loadBase()
  await loadGarmin()
})
</script>

<style scoped>
.family-profiles {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
}

/* 顶部栏 */
.fp-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fp-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.fp-title h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: var(--text);
}

.fp-title span {
  font-size: 13px;
  color: var(--muted);
}

.fp-add {
  flex-shrink: 0;
  padding: 9px 14px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 14px rgba(22, 119, 255, 0.28);
}

/* 搜索 */
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  height: 46px;
  border-radius: 14px;
  background: var(--card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.search-icon {
  font-size: 17px;
  opacity: 0.7;
}

.search-bar input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: var(--text);
}

/* 统计卡 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 14px;
  border-radius: 16px;
  background: var(--card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.stat-icon {
  font-size: 20px;
}

.stat-value {
  font-size: 22px;
  font-weight: 800;
  line-height: 1.15;
  color: var(--primary);
}

.stat-value small {
  font-size: 12px;
  font-weight: 700;
  margin-left: 2px;
}

.stat-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.stat-sub {
  font-size: 12px;
  color: var(--muted);
}

.stat-card.tone-green .stat-value { color: #16a34a; }
.stat-card.tone-orange .stat-value { color: #d97706; }
.stat-card.tone-purple .stat-value { color: #722ed1; }
.stat-card.tone-blue .stat-value { color: var(--primary); }

/* 卡片通用 */
.fp-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
}

.fp-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.fp-card-head strong {
  font-size: 17px;
}

.head-count {
  font-size: 13px;
  color: var(--muted);
  font-weight: 600;
}

/* 成员列表 */
.member-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.member-card {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: #f8fbff;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease, transform 0.1s ease;
}

.member-card:active {
  background: var(--primary-soft);
  transform: scale(0.99);
}

.member-avatar {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  font-size: 20px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, #36cfc9, #1677ff);
  flex-shrink: 0;
}

.member-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.member-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.member-name {
  font-size: 17px;
  font-weight: 800;
  color: var(--text);
}

.self-tag {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-soft);
}

.self-tag.light {
  color: #fff;
  background: rgba(255, 255, 255, 0.28);
}

.member-sub {
  font-size: 13px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.member-time {
  font-size: 12px;
  color: #94a3b8;
}

.chevron {
  flex-shrink: 0;
  font-size: 24px;
  color: #cbd5e1;
  line-height: 1;
}

/* 添加成员卡 */
.add-member-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 16px;
  border: 1.5px dashed var(--primary);
  border-radius: 16px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.am-icon {
  font-size: 20px;
  font-weight: 800;
}

/* 使用提示 */
.tip-card {
  display: flex;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  background: #eef6ff;
  border: 1px solid #d6e8ff;
}

.tip-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.tip-body strong {
  display: block;
  font-size: 15px;
  color: #0958d9;
  margin-bottom: 2px;
}

.tip-body p {
  margin: 0;
  font-size: 13px;
  color: #3b6bb0;
  line-height: 1.5;
}

/* 详情：患者头卡 */
.detail-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 18px;
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  box-shadow: 0 10px 22px rgba(22, 119, 255, 0.28);
}

.hero-avatar {
  display: grid;
  place-items: center;
  width: 58px;
  height: 58px;
  border-radius: 18px;
  font-size: 26px;
  font-weight: 800;
  background: rgba(255, 255, 255, 0.24);
  flex-shrink: 0;
}

.hero-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hero-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hero-name {
  font-size: 21px;
  font-weight: 800;
}

.hero-meta {
  font-size: 13px;
  opacity: 0.94;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}

.hero-tags .cond-tag {
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: rgba(255, 255, 255, 0.22);
}

.hero-tags .cond-tag.is-muted {
  background: rgba(255, 255, 255, 0.16);
}

.hero-badge {
  flex-shrink: 0;
  align-self: flex-start;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  background: rgba(255, 255, 255, 0.24);
}

/* 健康指标卡 */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 14px;
  border-radius: 16px;
  background: var(--card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.metric-icon {
  font-size: 20px;
}

.metric-value {
  font-size: 22px;
  font-weight: 800;
  line-height: 1.1;
  color: var(--text);
}

.metric-value small {
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
}

.metric-label {
  font-size: 13px;
  color: var(--muted);
  font-weight: 600;
}

.metric-card.tone-red .metric-value { color: #dc2626; }
.metric-card.tone-orange .metric-value { color: #d97706; }
.metric-card.tone-pink .metric-value { color: #eb2f96; }
.metric-card.tone-blue .metric-value { color: var(--primary); }

/* 详情 Tabs */
.detail-tabs {
  display: flex;
  gap: 6px;
  padding: 5px;
  border-radius: 14px;
  background: #eef2f7;
}

.detail-tabs button {
  flex: 1;
  padding: 9px 0;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.detail-tabs button.active {
  background: #fff;
  color: var(--primary);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
}

/* 详情面板 */
.detail-panel {
  padding: 4px 14px;
}

.info-list {
  display: flex;
  flex-direction: column;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 0;
  border-bottom: 1px solid #f0f4f9;
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 14px;
  color: var(--muted);
  flex-shrink: 0;
}

.info-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  text-align: right;
  word-break: break-all;
}

.info-value.is-sample {
  color: #94a3b8;
  font-weight: 600;
}

.sample-note {
  margin: -4px 0 0;
  text-align: center;
  font-size: 12px;
  color: #94a3b8;
}

/* 详情底部按钮 */
.detail-actions {
  display: flex;
  gap: 10px;
}

.act-btn {
  flex: 1;
  padding: 14px 0;
  border-radius: 14px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
}

.act-btn.edit {
  border: none;
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  box-shadow: 0 6px 14px rgba(22, 119, 255, 0.28);
}

.act-btn.del {
  border: 1px solid #fca5a5;
  color: #dc2626;
  background: #fff;
}

/* 对话框按钮 */
.dlg-btn {
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.dlg-btn.ghost {
  border: 1px solid var(--border);
  background: #fff;
  color: var(--muted);
  margin-right: 8px;
}

.dlg-btn.primary {
  border: none;
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0 14px;
}
</style>
