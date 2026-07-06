<template>
  <section>
    <div class="page-header">
      <div>
        <p class="eyebrow">Health Profile</p>
        <h1>健康档案管理</h1>
        <p class="subtext">维护患者基础信息、过敏史和紧急联系人。</p>
      </div>
      <el-button type="primary" size="large" @click="openCreate">新增档案</el-button>
    </div>

    <div class="section-card card data-table">
      <el-table :data="users" v-loading="loading" border table-layout="auto">
        <el-table-column prop="name" label="姓名" min-width="72" show-overflow-tooltip />
        <el-table-column prop="age" label="年龄" width="56" align="center" />
        <el-table-column prop="gender" label="性别" width="56" align="center" />
        <el-table-column prop="phone" label="电话" min-width="110" show-overflow-tooltip />
        <el-table-column prop="emergency_contact" label="紧急联系" min-width="96" show-overflow-tooltip />
        <el-table-column label="操作" fixed="right" width="170" align="center">
          <template #default="scope">
            <div class="table-actions">
              <el-button link type="primary" @click="openView(scope.row)">查看</el-button>
              <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
              <el-button link type="danger" @click="removeUser(scope.row.id)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="720px">
      <el-form :model="form" label-width="140px" size="large" :disabled="mode === 'view'">
        <el-row :gutter="18">
          <el-col :span="12"><el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="年龄"><el-input-number v-model="form.age" :min="0" :max="130" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="性别"><el-select v-model="form.gender"><el-option label="男" value="男" /><el-option label="女" value="女" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="身高"><el-input-number v-model="form.height" :min="0" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="体重"><el-input-number v-model="form.weight" :min="0" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="联系电话"><el-input v-model="form.phone" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="紧急联系人"><el-input v-model="form.emergency_contact" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="紧急联系人电话"><el-input v-model="form.emergency_phone" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="过敏史"><el-input v-model="form.allergy" type="textarea" :rows="3" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button>
        <el-button v-if="mode !== 'view'" type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { createUser, deleteUser, getUsers, updateUser } from '../api/users'

const users = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const dialogTitle = ref('新增档案')
const mode = ref('create')
const editingId = ref(null)

const emptyForm = () => ({
  name: '',
  age: null,
  gender: '',
  height: null,
  weight: null,
  phone: '',
  emergency_contact: '',
  emergency_phone: '',
  allergy: '',
  remark: ''
})

const form = reactive(emptyForm())

const resetForm = (data = emptyForm()) => {
  Object.assign(form, data)
}

const loadUsers = async () => {
  loading.value = true
  try {
    const { data } = await getUsers()
    users.value = data
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  mode.value = 'create'
  editingId.value = null
  dialogTitle.value = '新增健康档案'
  resetForm()
  dialogVisible.value = true
}

const openEdit = (row) => {
  mode.value = 'edit'
  editingId.value = row.id
  dialogTitle.value = '编辑健康档案'
  resetForm(row)
  dialogVisible.value = true
}

const openView = (row) => {
  mode.value = 'view'
  dialogTitle.value = '查看健康档案'
  resetForm(row)
  dialogVisible.value = true
}

const submitForm = async () => {
  if (!form.name.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (mode.value === 'create') {
    await createUser(form)
  } else {
    await updateUser(editingId.value, form)
  }
  ElMessage.success('保存成功')
  dialogVisible.value = false
  loadUsers()
}

const removeUser = async (id) => {
  await ElMessageBox.confirm('删除后将同步删除关联病例，是否继续？', '确认删除', { type: 'warning' })
  await deleteUser(id)
  ElMessage.success('删除成功')
  loadUsers()
}

onMounted(loadUsers)
</script>
