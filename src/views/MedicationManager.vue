<template>
  <section>
    <div class="page-header">
      <div>
        <p class="eyebrow">Medication Manager</p>
        <h1>药物管理</h1>
        <p class="subtext">管理患者长期用药、剂量、频率和服用时间。</p>
      </div>
      <el-button type="primary" size="large" @click="openCreate">新增药物</el-button>
    </div>

    <div class="section-card card filter-card">
      <el-select v-model="selectedUserId" clearable placeholder="按患者筛选" size="large" @change="loadMedications">
        <el-option v-for="user in users" :key="user.id" :label="`${user.name} (ID: ${user.id})`" :value="user.id" />
      </el-select>
    </div>

    <div class="section-card card data-table">
      <el-table :data="medications" v-loading="loading" border table-layout="auto">
        <el-table-column prop="name" label="药名" min-width="96" show-overflow-tooltip />
        <el-table-column prop="dosage" label="剂量" width="72" show-overflow-tooltip />
        <el-table-column prop="frequency" label="频率" min-width="88" show-overflow-tooltip />
        <el-table-column label="时间" min-width="120" show-overflow-tooltip>
          <template #default="scope">
            {{ formatTakeTimes(scope.row) }}
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="88" show-overflow-tooltip />
        <el-table-column label="操作" fixed="right" width="170" align="center">
          <template #default="scope">
            <div class="table-actions">
              <el-button link type="primary" @click="openView(scope.row)">查看</el-button>
              <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
              <el-button link type="danger" @click="removeMedication(scope.row.id)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="680px">
      <el-alert v-if="!users.length" title="请先新增健康档案，再添加药物。" type="info" show-icon />
      <el-form :model="form" label-width="110px" size="large" :disabled="mode === 'view'">
        <el-form-item label="患者"><el-select v-model="form.user_id" placeholder="请选择患者"><el-option v-for="user in users" :key="user.id" :label="`${user.name} (ID: ${user.id})`" :value="user.id" /></el-select></el-form-item>
        <el-form-item label="药物名称"><el-input v-model="form.name" placeholder="例如：氨氯地平" /></el-form-item>
        <el-form-item label="剂量"><el-input v-model="form.dosage" placeholder="例如：5mg" /></el-form-item>
        <el-form-item label="服用频率"><el-input v-model="form.frequency" placeholder="例如：每日两次" /></el-form-item>
        <el-form-item label="服用时间">
          <div class="take-times-editor">
            <div v-for="(time, index) in form.take_times" :key="index" class="take-time-row">
              <el-time-picker
                v-model="form.take_times[index]"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="请选择时间"
              />
              <el-button
                v-if="mode !== 'view'"
                link
                type="danger"
                :disabled="form.take_times.length <= 1"
                @click="removeTakeTime(index)"
              >
                删除
              </el-button>
            </div>
            <el-button v-if="mode !== 'view'" link type="primary" @click="addTakeTime">+ 添加时间</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" :rows="3" placeholder="例如：降压药" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button v-if="mode !== 'view'" type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { createMedication, deleteMedication, getMedications, updateMedication } from '../api/medications'
import { getUsers } from '../api/users'

const medications = ref([])
const users = ref([])
const loading = ref(false)
const saving = ref(false)
const selectedUserId = ref(null)
const dialogVisible = ref(false)
const dialogTitle = ref('新增药物')
const mode = ref('create')
const editingId = ref(null)

const emptyForm = () => ({
  user_id: null,
  name: '',
  dosage: '',
  frequency: '',
  take_times: [''],
  note: '',
})

const form = reactive(emptyForm())

const resetForm = (data = emptyForm()) => {
  const takeTimes = Array.isArray(data.take_times) && data.take_times.length
    ? [...data.take_times]
    : data.take_time
      ? [data.take_time]
      : ['']
  Object.assign(form, { ...emptyForm(), ...data, take_times: takeTimes })
}

const formatTakeTimes = (row) => {
  const times = Array.isArray(row.take_times) && row.take_times.length
    ? row.take_times
    : row.take_time
      ? [row.take_time]
      : []
  return times.length ? times.join('、') : '-'
}

const addTakeTime = () => {
  form.take_times.push('')
}

const removeTakeTime = (index) => {
  if (form.take_times.length <= 1) return
  form.take_times.splice(index, 1)
}

const loadUsers = async () => {
  const { data } = await getUsers()
  users.value = data
}

const loadMedications = async () => {
  loading.value = true
  try {
    const params = selectedUserId.value ? { user_id: selectedUserId.value } : {}
    const { data } = await getMedications(params)
    medications.value = data
  } catch (error) {
    ElMessage.error('药物列表加载失败，请确认后端服务已启动')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  mode.value = 'create'
  editingId.value = null
  dialogTitle.value = '新增药物'
  resetForm({ ...emptyForm(), user_id: selectedUserId.value })
  dialogVisible.value = true
}

const openEdit = (row) => {
  mode.value = 'edit'
  editingId.value = row.id
  dialogTitle.value = '编辑药物'
  resetForm(row)
  dialogVisible.value = true
}

const openView = (row) => {
  mode.value = 'view'
  dialogTitle.value = '查看药物'
  resetForm(row)
  dialogVisible.value = true
}

const buildPayload = () => {
  const takeTimes = form.take_times.map((item) => (item || '').trim()).filter(Boolean)
  return {
    user_id: form.user_id,
    name: form.name.trim(),
    dosage: form.dosage,
    frequency: form.frequency,
    take_times: takeTimes,
    note: form.note,
  }
}

const submitForm = async () => {
  if (!form.user_id) {
    ElMessage.warning('请选择患者')
    return
  }
  if (!form.name.trim()) {
    ElMessage.warning('请填写药物名称')
    return
  }
  const payload = buildPayload()
  if (!payload.take_times.length) {
    ElMessage.warning('请至少添加一个服用时间')
    return
  }
  saving.value = true
  try {
    if (mode.value === 'create') {
      await createMedication(payload)
    } else {
      await updateMedication(editingId.value, payload)
    }
    ElMessage.success('保存成功')
    dialogVisible.value = false
    loadMedications()
  } catch (error) {
    ElMessage.error('保存失败，请确认后端服务已启动')
  } finally {
    saving.value = false
  }
}

const removeMedication = async (id) => {
  await ElMessageBox.confirm('确认删除该药物？', '确认删除', { type: 'warning' })
  await deleteMedication(id)
  ElMessage.success('删除成功')
  loadMedications()
}

onMounted(async () => {
  await loadUsers()
  await loadMedications()
})
</script>

<style scoped>
.filter-card {
  margin-bottom: 18px;
}

.filter-card .el-select {
  width: min(360px, 100%);
}

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
</style>
