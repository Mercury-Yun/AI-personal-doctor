<template>
  <section class="family-meds">
    <header class="fm-header">
      <button type="button" class="back-btn" aria-label="返回首页" @click="goFamily">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>
      <div class="fm-title">
        <h1>提醒管理</h1>
        <span>设置用药方案与服药时间，按时提醒老人用药</span>
      </div>
      <button type="button" class="fm-add" :disabled="!patient" @click="openCreate">＋ 添加药物</button>
    </header>

    <div v-if="patient" class="fm-card patient-card">
      <div class="patient-avatar">{{ patientInitial }}</div>
      <div class="patient-info">
        <div class="patient-name-row">
          <strong class="patient-name">{{ patient.name }}</strong>
          <span v-if="patient.age != null" class="patient-meta">{{ patient.age }}岁</span>
          <span v-if="patient.gender" class="patient-meta">{{ patient.gender }}</span>
        </div>
        <div class="patient-tags">
          <span v-for="tag in patientConditions" :key="tag" class="cond-tag">{{ tag }}</span>
          <span v-if="!patientConditions.length" class="cond-tag is-muted">暂无慢性病</span>
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

    <div class="fm-card">
      <div class="fm-card-head">
        <strong>用药方案</strong>
        <span class="head-count">{{ medications.length }} 种</span>
      </div>
      <div v-if="medications.length" class="med-list">
        <article v-for="m in medications" :key="m.id" class="med-card">
          <div class="mc-top">
            <span class="mc-icon">💊</span>
            <div class="mc-head">
              <strong class="mc-name">{{ m.name }}</strong>
              <span class="mc-dosage">{{ m.dosage || '按医嘱' }}</span>
            </div>
            <span v-if="m.note && m.note.trim()" class="mc-cat">{{ m.note }}</span>
          </div>
          <div class="mc-row">
            <span class="mc-label">用法</span>
            <span class="mc-value">{{ m.frequency && m.frequency.trim() ? m.frequency : '按医嘱服用' }}</span>
          </div>
          <div class="mc-row">
            <span class="mc-label">服药时间</span>
            <div class="mc-times">
              <span v-for="(t, i) in takeTimesOf(m)" :key="i" class="time-chip">
                <span class="time-ic" aria-hidden="true">{{ timeIcon(t) }}</span>{{ t }}
              </span>
              <span v-if="!takeTimesOf(m).length" class="time-chip is-empty">未设置</span>
            </div>
          </div>
          <div class="mc-actions">
            <button type="button" class="mc-btn edit" @click="openEdit(m)">编辑</button>
            <button type="button" class="mc-btn del" @click="removeMedication(m)">删除</button>
          </div>
        </article>
      </div>
      <el-empty v-else :description="patient ? '暂无用药方案，点击右上角添加' : '请先在健康档案中添加患者'" :image-size="52" />
    </div>

    <!-- 新增 / 编辑药物 -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="92%" top="6vh" class="fm-dialog">
      <el-form :model="form" label-position="top" size="large">
        <el-form-item label="药物名称"><el-input v-model="form.name" placeholder="例如：氨氯地平" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="剂量"><el-input v-model="form.dosage" placeholder="例如：5mg" /></el-form-item>
          <el-form-item label="分类"><el-input v-model="form.note" placeholder="例如：降压药" /></el-form-item>
        </div>
        <el-form-item label="服用频率"><el-input v-model="form.frequency" placeholder="例如：每日两次" /></el-form-item>
        <el-form-item label="服药时间">
          <div class="take-times-editor">
            <div v-for="(time, index) in form.take_times" :key="index" class="take-time-row">
              <el-time-picker
                v-model="form.take_times[index]"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="请选择时间"
              />
              <button
                type="button"
                class="tt-del"
                :disabled="form.take_times.length <= 1"
                @click="removeTakeTime(index)"
              >
                删除
              </button>
            </div>
            <button type="button" class="tt-add" @click="addTakeTime">＋ 添加时间</button>
          </div>
        </el-form-item>
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
import { createMedication, deleteMedication, getMedications, updateMedication } from '../api/medications'
import { getTodayReminders } from '../api/device'
import { getUsers } from '../api/users'

const router = useRouter()

const users = ref([])
const medications = ref([])
const reminders = ref([])
const currentIndex = ref(0)

const dialogVisible = ref(false)
const dialogMode = ref('create')
const editingId = ref(null)

const NONE_CONDITION = new Set(['无', '暂无', '无病史', '无慢性病', '无慢性疾病', '无特殊', '否认', '健康', '正常', '-', 'none'])

const patient = computed(() => users.value[currentIndex.value] || null)
const patientInitial = computed(() => (patient.value?.name || '患').slice(0, 1))

const patientConditions = computed(() => {
  const p = patient.value
  if (!p) return []
  const raw = p.chronic_diseases || ''
  return raw
    .split(/[，,、;；·\/\s]+/)
    .map((s) => s.trim())
    .filter((s) => s && !NONE_CONDITION.has(s))
    .slice(0, 4)
})

const takeTimesOf = (m) => {
  if (Array.isArray(m.take_times) && m.take_times.length) return m.take_times
  return m.take_time ? [m.take_time] : []
}

const timeIcon = (t) => {
  const h = parseInt(String(t).split(':')[0], 10)
  if (Number.isNaN(h)) return '⏰'
  return h >= 6 && h < 18 ? '☀️' : '🌙'
}

// ---- 今日提醒统计（按当前患者过滤）----
const todayReminders = computed(() => {
  const p = patient.value
  return p ? reminders.value.filter((r) => r.user_id === p.id) : reminders.value
})
const takenCount = computed(() => todayReminders.value.filter((r) => r.status === 'taken').length)
const totalDoses = computed(() => todayReminders.value.length)
const adherence = computed(() => (totalDoses.value ? Math.round((takenCount.value / totalDoses.value) * 100) : null))

const statCards = computed(() => [
  { key: 'kinds', icon: '💊', value: medications.value.length, suffix: '种', label: '用药品种', tone: 'blue' },
  { key: 'doses', icon: '📅', value: totalDoses.value, suffix: '次', label: '今日应服', tone: 'purple' },
  { key: 'taken', icon: '✅', value: totalDoses.value ? `${takenCount.value}/${totalDoses.value}` : '—', label: '今日已服', tone: 'green' },
  { key: 'adherence', icon: '📈', value: adherence.value == null ? '—' : adherence.value, suffix: adherence.value == null ? '' : '%', label: '用药依从性', tone: 'orange' },
])

// ---- 表单 ----
const emptyForm = () => ({
  name: '', dosage: '', frequency: '', note: '', take_times: [''],
})
const form = reactive(emptyForm())
const dialogTitle = computed(() => (dialogMode.value === 'create' ? '添加药物' : '编辑药物'))

const resetForm = (data = emptyForm()) => {
  const takeTimes = Array.isArray(data.take_times) && data.take_times.length
    ? [...data.take_times]
    : data.take_time
      ? [data.take_time]
      : ['']
  Object.assign(form, { ...emptyForm(), ...data, take_times: takeTimes })
}

const openCreate = () => {
  if (!patient.value) {
    ElMessage.warning('请先在健康档案中添加患者')
    return
  }
  dialogMode.value = 'create'
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

const openEdit = (m) => {
  dialogMode.value = 'edit'
  editingId.value = m.id
  resetForm(m)
  dialogVisible.value = true
}

const addTakeTime = () => form.take_times.push('')
const removeTakeTime = (index) => {
  if (form.take_times.length <= 1) return
  form.take_times.splice(index, 1)
}

const buildPayload = () => ({
  user_id: patient.value.id,
  name: form.name.trim(),
  dosage: form.dosage,
  frequency: form.frequency,
  note: form.note,
  take_times: form.take_times.map((t) => (t || '').trim()).filter(Boolean),
})

const submitForm = async () => {
  if (!patient.value) {
    ElMessage.warning('请先在健康档案中添加患者')
    return
  }
  if (!form.name.trim()) {
    ElMessage.warning('请填写药物名称')
    return
  }
  const payload = buildPayload()
  if (!payload.take_times.length) {
    ElMessage.warning('请至少添加一个服药时间')
    return
  }
  try {
    if (dialogMode.value === 'create') {
      await createMedication(payload)
    } else {
      await updateMedication(editingId.value, payload)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await loadMedications()
    await loadReminders()
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  }
}

const removeMedication = async (m) => {
  try {
    await ElMessageBox.confirm(`确认删除「${m.name}」的用药提醒？`, '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteMedication(m.id)
    ElMessage.success('已删除')
    await loadMedications()
    await loadReminders()
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

const switchPatient = () => {
  if (users.value.length < 2) return
  currentIndex.value = (currentIndex.value + 1) % users.value.length
  void loadMedications()
}

const goFamily = () => router.push('/family')

const loadMedications = async () => {
  const p = patient.value
  if (!p) {
    medications.value = []
    return
  }
  try {
    const { data } = await getMedications({ user_id: p.id })
    medications.value = data || []
  } catch {
    medications.value = []
  }
}

const loadReminders = async () => {
  try {
    const { data } = await getTodayReminders()
    reminders.value = data || []
  } catch {
    /* 保留上次数据 */
  }
}

const loadBase = async () => {
  const [uRes] = await Promise.allSettled([getUsers()])
  if (uRes.status === 'fulfilled') users.value = uRes.value.data || []
}

onMounted(async () => {
  await loadBase()
  await Promise.all([loadMedications(), loadReminders()])
})
</script>

<style scoped>
.family-meds {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
}

/* 顶部栏 */
.fm-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fm-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.fm-title h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: var(--text);
}

.fm-title span {
  font-size: 13px;
  color: var(--muted);
}

.fm-add {
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

.fm-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

/* 卡片通用 */
.fm-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
}

.fm-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.fm-card-head strong {
  font-size: 17px;
}

.head-count {
  font-size: 13px;
  color: var(--muted);
  font-weight: 600;
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
  color: var(--primary);
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
  text-align: center;
}

.stat-card.tone-green .stat-value { color: #16a34a; }
.stat-card.tone-orange .stat-value { color: #d97706; }
.stat-card.tone-purple .stat-value { color: #722ed1; }
.stat-card.tone-blue .stat-value { color: var(--primary); }

/* 药物卡 */
.med-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.med-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  background: #f8fbff;
  padding: 12px 14px;
}

.mc-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mc-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  font-size: 22px;
  background: var(--primary-soft);
  flex-shrink: 0;
}

.mc-head {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mc-name {
  font-size: 17px;
  font-weight: 800;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-dosage {
  font-size: 13px;
  color: var(--muted);
}

.mc-cat {
  flex-shrink: 0;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  color: #0958d9;
  background: #e8f3ff;
}

.mc-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.mc-label {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--muted);
  min-width: 56px;
}

.mc-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.mc-times {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.time-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
  background: #fff;
  border: 1px solid var(--border);
}

.time-chip.is-empty {
  color: var(--muted);
  font-weight: 600;
}

.time-ic {
  font-size: 13px;
}

.mc-actions {
  display: flex;
  gap: 10px;
  margin-top: 12px;
}

.mc-btn {
  flex: 1;
  padding: 9px 0;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.mc-btn.edit {
  border: none;
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
}

.mc-btn.del {
  border: 1px solid #fca5a5;
  color: #dc2626;
  background: #fff;
}

/* 时间编辑器 */
.take-times-editor {
  display: grid;
  gap: 10px;
  width: 100%;
}

.take-time-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tt-del {
  border: none;
  background: none;
  color: #dc2626;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.tt-del:disabled {
  color: #cbd5e1;
  cursor: not-allowed;
}

.tt-add {
  justify-self: start;
  border: none;
  background: none;
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
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
