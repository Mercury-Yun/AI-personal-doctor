<template>
  <section class="family-records">
    <!-- 列表页 -->
    <template v-if="view === 'list'">
      <header class="fr-header">
        <button type="button" class="back-btn" aria-label="返回首页" @click="goFamily">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div class="fr-title">
          <h1>病例管理</h1>
          <span>记录每一次就诊，辅助 AI 问诊</span>
        </div>
        <button type="button" class="fr-add" :disabled="!patient" @click="openCreateCase">＋ 新增病例</button>
      </header>

      <div v-if="patient" class="fr-card patient-card">
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
          <strong class="stat-value">{{ s.value }}</strong>
          <span class="stat-label">{{ s.label }}</span>
        </div>
      </div>

      <div class="search-bar">
        <span class="search-icon" aria-hidden="true">🔍</span>
        <input v-model.trim="keyword" type="search" placeholder="搜索主诉 / 医院 / 科室 / 医生" />
      </div>

      <div class="filter-row">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="true"
          class="fr-date"
        />
        <div class="type-chips">
          <button
            v-for="t in typeChips"
            :key="t.value"
            type="button"
            :class="{ active: filterType === t.value }"
            @click="filterType = t.value"
          >
            {{ t.label }}
          </button>
        </div>
      </div>

      <div class="fr-card">
        <div class="fr-card-head">
          <strong>就诊记录</strong>
          <span class="head-count">{{ filteredCases.length }} 条</span>
        </div>
        <div v-if="filteredCases.length" class="case-list">
          <button
            v-for="c in filteredCases"
            :key="c.id"
            type="button"
            class="case-card"
            @click="openDetail(c.id)"
          >
            <div class="cc-top">
              <span class="cc-date">{{ c.visit_date || '未填日期' }}</span>
              <span class="cc-type" :class="`vt-${visitTone(c.visit_type)}`">{{ c.visit_type || '门诊' }}</span>
            </div>
            <strong class="cc-complaint">{{ c.chief_complaint || '（无主诉记录）' }}</strong>
            <div class="cc-meta">
              <span v-if="c.hospital">🏥 {{ c.hospital }}</span>
              <span v-if="c.department">🩺 {{ c.department }}</span>
              <span v-if="c.doctor">👨‍⚕️ {{ c.doctor }}</span>
            </div>
            <span class="chevron" aria-hidden="true">›</span>
          </button>
        </div>
        <el-empty v-else :description="patient ? '暂无病例，点击右上角新增' : '请先在健康档案中添加患者'" :image-size="52" />
      </div>
    </template>

    <!-- 检查详情子页 -->
    <template v-else-if="view === 'exam' && activeExam">
      <header class="fr-header">
        <button type="button" class="back-btn" aria-label="返回病例" @click="view = 'detail'">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div class="fr-title">
          <h1>检查详情</h1>
          <span>{{ activeExam.name }}</span>
        </div>
      </header>

      <div class="fr-card">
        <div class="info-list">
          <div class="info-row"><span class="info-label">检查名称</span><span class="info-value">{{ activeExam.name }}</span></div>
          <div class="info-row"><span class="info-label">检查时间</span><span class="info-value">{{ dash(activeExam.exam_time) }}</span></div>
          <div class="info-row"><span class="info-label">检查医院</span><span class="info-value">{{ dash(activeExam.hospital) }}</span></div>
        </div>
        <div class="result-block">
          <span class="block-label">结果描述</span>
          <p class="block-text">{{ activeExam.result || '暂无文字结果' }}</p>
        </div>
      </div>

      <div class="fr-card">
        <div class="fr-card-head">
          <strong>检查图片</strong>
          <button type="button" class="mini-btn" @click="triggerUpload('exam', activeExam.id)">＋ 上传图片</button>
        </div>
        <div v-if="activeExam.attachments && activeExam.attachments.length" class="attach-grid">
          <div v-for="a in activeExam.attachments" :key="a.id" class="attach-cell">
            <el-image
              v-if="a.kind === 'image'"
              :src="attachmentRawUrl(a.id)"
              :preview-src-list="examImageList"
              :initial-index="examImageIndex(a.id)"
              fit="cover"
              class="attach-img"
            />
            <a v-else class="attach-file" :href="attachmentDownloadUrl(a.id)" target="_blank" rel="noopener">
              <span class="file-ic">📄</span>
              <span class="file-name">{{ a.file_name }}</span>
            </a>
            <div class="attach-actions">
              <a class="attach-op" :href="attachmentDownloadUrl(a.id)" target="_blank" rel="noopener">下载</a>
              <button type="button" class="attach-op del" @click="removeAttachment(a)">删除</button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无检查图片" :image-size="46" />
      </div>
    </template>

    <!-- 病例详情页 -->
    <template v-else-if="view === 'detail' && detail">
      <header class="fr-header">
        <button type="button" class="back-btn" aria-label="返回列表" @click="backToList">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div class="fr-title">
          <h1>病例详情</h1>
          <span>{{ detail.visit_date }} · {{ detail.visit_type || '门诊' }}</span>
        </div>
        <button type="button" class="fr-add" @click="openEditCase">编辑</button>
      </header>

      <div class="detail-hero">
        <div class="hero-avatar">{{ patientInitial }}</div>
        <div class="hero-info">
          <strong class="hero-name">{{ patient?.name }}</strong>
          <span class="hero-meta">{{ detail.hospital || '未填医院' }} · {{ detail.department || '未填科室' }}</span>
          <span class="hero-diag">诊断：{{ detail.diagnosis || '暂无' }}</span>
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

      <!-- 病历信息 -->
      <div v-if="activeTab === 'info'" class="fr-card">
        <div class="info-list">
          <div v-for="row in infoRows" :key="row.label" class="info-row block">
            <span class="info-label">{{ row.label }}</span>
            <span class="info-value">{{ row.value }}</span>
          </div>
        </div>
      </div>

      <!-- 检查结果 -->
      <div v-else-if="activeTab === 'exams'" class="fr-card">
        <div class="fr-card-head">
          <strong>检查结果</strong>
          <button type="button" class="mini-btn" @click="openCreateExam">＋ 新增检查</button>
        </div>
        <div v-if="detail.examinations.length" class="sub-list">
          <div v-for="e in detail.examinations" :key="e.id" class="sub-card">
            <button type="button" class="sub-main" @click="openExam(e)">
              <div class="sub-head">
                <strong>{{ e.name }}</strong>
                <span v-if="e.attachments && e.attachments.length" class="img-badge">🖼 {{ e.attachments.length }}</span>
              </div>
              <div class="sub-meta">
                <span v-if="e.exam_time">🕒 {{ e.exam_time }}</span>
                <span v-if="e.hospital">🏥 {{ e.hospital }}</span>
              </div>
              <p v-if="e.result" class="sub-text">{{ e.result }}</p>
            </button>
            <div class="sub-ops">
              <button type="button" class="sub-op" @click="openEditExam(e)">编辑</button>
              <button type="button" class="sub-op del" @click="removeExam(e)">删除</button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无检查记录" :image-size="46" />
      </div>

      <!-- 处方记录 -->
      <div v-else-if="activeTab === 'prescriptions'" class="fr-card">
        <div class="fr-card-head">
          <strong>处方记录</strong>
          <button type="button" class="mini-btn" @click="openCreatePrescription">＋ 新增处方</button>
        </div>
        <div v-if="detail.prescriptions.length" class="sub-list">
          <div v-for="p in detail.prescriptions" :key="p.id" class="sub-card">
            <div class="sub-head">
              <strong>开具日期：{{ p.issued_date || '未填' }}</strong>
              <div class="sub-ops inline">
                <button type="button" class="sub-op" @click="openEditPrescription(p)">编辑</button>
                <button type="button" class="sub-op del" @click="removePrescription(p)">删除</button>
              </div>
            </div>
            <table v-if="p.drugs && p.drugs.length" class="drug-table">
              <thead>
                <tr><th>药品</th><th>剂量</th><th>用法</th><th>频率</th><th>疗程</th></tr>
              </thead>
              <tbody>
                <tr v-for="d in p.drugs" :key="d.id">
                  <td>{{ d.name }}</td>
                  <td>{{ d.dosage || '-' }}</td>
                  <td>{{ d.usage || '-' }}</td>
                  <td>{{ d.frequency || '-' }}</td>
                  <td>{{ d.duration || '-' }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="p.note" class="sub-text">备注：{{ p.note }}</p>
            <div class="rx-images">
              <el-image
                v-for="a in (p.attachments || []).filter((x) => x.kind === 'image')"
                :key="a.id"
                :src="attachmentRawUrl(a.id)"
                :preview-src-list="rxImageList(p)"
                :initial-index="rxImageIndex(p, a.id)"
                fit="cover"
                class="rx-img"
              />
              <button type="button" class="rx-add" @click="triggerUpload('prescription', p.id)">＋ 处方图片</button>
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无处方记录" :image-size="46" />
      </div>

      <!-- 随访记录 -->
      <div v-else-if="activeTab === 'followups'" class="fr-card">
        <div class="fr-card-head">
          <strong>随访记录</strong>
          <button type="button" class="mini-btn" @click="openCreateFollowUp">＋ 新增随访</button>
        </div>
        <el-timeline v-if="detail.follow_ups.length" class="fr-timeline">
          <el-timeline-item
            v-for="f in sortedFollowUps"
            :key="f.id"
            :timestamp="f.follow_date || ''"
            :type="f.completed ? 'success' : 'primary'"
            placement="top"
          >
            <div class="fu-card">
              <div class="fu-head">
                <span class="fu-status" :class="f.completed ? 'done' : 'pending'">{{ f.completed ? '已完成' : '进行中' }}</span>
                <div class="sub-ops inline">
                  <button type="button" class="sub-op" @click="openEditFollowUp(f)">编辑</button>
                  <button type="button" class="sub-op del" @click="removeFollowUp(f)">删除</button>
                </div>
              </div>
              <p v-if="f.advice" class="fu-row"><b>医生建议：</b>{{ f.advice }}</p>
              <p v-if="f.recovery" class="fu-row"><b>康复情况：</b>{{ f.recovery }}</p>
              <p v-if="f.next_plan" class="fu-row"><b>下次复诊：</b>{{ f.next_plan }}</p>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无随访记录" :image-size="46" />
      </div>

      <!-- AI 病例摘要 -->
      <div v-else-if="activeTab === 'summary'" class="fr-card">
        <div class="fr-card-head">
          <strong>AI 病例摘要</strong>
          <button type="button" class="mini-btn" :disabled="summaryLoading" @click="generateSummary">
            {{ summaryLoading ? '生成中…' : summary ? '重新生成' : '生成摘要' }}
          </button>
        </div>
        <div v-if="summary" class="summary-box">
          <div class="sum-row"><span class="sum-label">疾病总结</span><span class="sum-value">{{ summary.main_disease || '—' }}</span></div>
          <div class="sum-row"><span class="sum-label">病史</span><span class="sum-value">{{ summary.history || '—' }}</span></div>
          <div class="sum-row"><span class="sum-label">最近就诊</span><span class="sum-value">{{ summary.recent_visit || '—' }}</span></div>
          <div class="sum-row"><span class="sum-label">最近检查</span><span class="sum-value">{{ summary.recent_exam || '—' }}</span></div>
          <div class="sum-row"><span class="sum-label">当前治疗</span><span class="sum-value">{{ summary.current_treatment || '—' }}</span></div>
          <div class="sum-row"><span class="sum-label">医生建议</span><span class="sum-value">{{ summary.doctor_advice || '—' }}</span></div>
          <div class="sum-row"><span class="sum-label">复查建议</span><span class="sum-value">{{ summary.follow_up || '—' }}</span></div>
          <div class="sum-row">
            <span class="sum-label">风险提示</span>
            <div class="sum-value">
              <span v-for="(r, i) in summary.risk" :key="i" class="risk-tag">{{ r }}</span>
              <span v-if="!summary.risk || !summary.risk.length">—</span>
            </div>
          </div>
        </div>
        <el-empty v-else :description="summaryLoading ? '正在生成，请稍候…' : '点击「生成摘要」由 AI 实时总结本病例（不保存）'" :image-size="52" />
      </div>

      <div class="detail-actions">
        <button type="button" class="act-btn del" @click="removeCase">删除病例</button>
      </div>
    </template>

    <!-- 病例表单 -->
    <el-dialog v-model="caseDialog" :title="editingCaseId ? '编辑病例' : '新增病例'" width="92%" top="6vh" class="fr-dialog">
      <el-form :model="caseForm" label-position="top" size="large">
        <div class="form-grid">
          <el-form-item label="就诊日期">
            <el-date-picker v-model="caseForm.visit_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
          </el-form-item>
          <el-form-item label="就诊类型">
            <el-select v-model="caseForm.visit_type" placeholder="选择">
              <el-option v-for="t in VISIT_TYPES" :key="t" :label="t" :value="t" />
            </el-select>
          </el-form-item>
          <el-form-item label="医院"><el-input v-model="caseForm.hospital" placeholder="就诊医院" /></el-form-item>
          <el-form-item label="科室"><el-input v-model="caseForm.department" placeholder="就诊科室" /></el-form-item>
          <el-form-item label="医生"><el-input v-model="caseForm.doctor" placeholder="接诊医生" /></el-form-item>
          <el-form-item label="手术名称（可选）"><el-input v-model="caseForm.surgery_name" placeholder="如无可留空" /></el-form-item>
        </div>
        <el-form-item label="主诉"><el-input v-model="caseForm.chief_complaint" type="textarea" :rows="2" placeholder="患者主要不适" /></el-form-item>
        <el-form-item label="现病史"><el-input v-model="caseForm.present_illness" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="既往史"><el-input v-model="caseForm.past_history" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="体格检查"><el-input v-model="caseForm.physical_exam" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="临床诊断"><el-input v-model="caseForm.diagnosis" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="医生建议"><el-input v-model="caseForm.doctor_advice" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="医生备注"><el-input v-model="caseForm.doctor_note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <button type="button" class="dlg-btn ghost" @click="caseDialog = false">取消</button>
        <button type="button" class="dlg-btn primary" @click="submitCase">保存</button>
      </template>
    </el-dialog>

    <!-- 检查表单 -->
    <el-dialog v-model="examDialog" :title="editingExamId ? '编辑检查' : '新增检查'" width="92%" top="8vh" class="fr-dialog">
      <el-form :model="examForm" label-position="top" size="large">
        <el-form-item label="检查名称"><el-input v-model="examForm.name" placeholder="例如：血常规 / 心电图" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="检查时间">
            <el-date-picker v-model="examForm.exam_time" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
          </el-form-item>
          <el-form-item label="检查医院"><el-input v-model="examForm.hospital" placeholder="检查医院" /></el-form-item>
        </div>
        <el-form-item label="结果描述"><el-input v-model="examForm.result" type="textarea" :rows="3" placeholder="检查结果文字描述（图片可稍后上传）" /></el-form-item>
      </el-form>
      <template #footer>
        <button type="button" class="dlg-btn ghost" @click="examDialog = false">取消</button>
        <button type="button" class="dlg-btn primary" @click="submitExam">保存</button>
      </template>
    </el-dialog>

    <!-- 处方表单 -->
    <el-dialog v-model="prescriptionDialog" :title="editingPrescriptionId ? '编辑处方' : '新增处方'" width="92%" top="6vh" class="fr-dialog">
      <el-form :model="prescriptionForm" label-position="top" size="large">
        <el-form-item label="开具日期">
          <el-date-picker v-model="prescriptionForm.issued_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="药品列表">
          <div class="drug-editor">
            <div v-for="(d, i) in prescriptionForm.drugs" :key="i" class="drug-row">
              <el-input v-model="d.name" placeholder="药品名称" class="drug-name" />
              <el-input v-model="d.dosage" placeholder="剂量" />
              <el-input v-model="d.usage" placeholder="用法" />
              <el-input v-model="d.frequency" placeholder="频率" />
              <el-input v-model="d.duration" placeholder="疗程" />
              <button type="button" class="tt-del" @click="removeDrug(i)">删除</button>
            </div>
            <button type="button" class="tt-add" @click="addDrug">＋ 添加药品</button>
          </div>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="prescriptionForm.note" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <button type="button" class="dlg-btn ghost" @click="prescriptionDialog = false">取消</button>
        <button type="button" class="dlg-btn primary" @click="submitPrescription">保存</button>
      </template>
    </el-dialog>

    <!-- 随访表单 -->
    <el-dialog v-model="followUpDialog" :title="editingFollowUpId ? '编辑随访' : '新增随访'" width="92%" top="8vh" class="fr-dialog">
      <el-form :model="followUpForm" label-position="top" size="large">
        <el-form-item label="随访日期">
          <el-date-picker v-model="followUpForm.follow_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="医生建议"><el-input v-model="followUpForm.advice" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="康复情况"><el-input v-model="followUpForm.recovery" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="下次复诊计划"><el-input v-model="followUpForm.next_plan" placeholder="例如：1个月后复查" /></el-form-item>
        <el-form-item label="是否完成">
          <el-switch v-model="followUpForm.completed" />
        </el-form-item>
      </el-form>
      <template #footer>
        <button type="button" class="dlg-btn ghost" @click="followUpDialog = false">取消</button>
        <button type="button" class="dlg-btn primary" @click="submitFollowUp">保存</button>
      </template>
    </el-dialog>

    <input ref="fileInput" type="file" accept="image/*,.pdf" multiple hidden @change="onFileChange" />
  </section>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getUsers } from '../api/users'
import {
  attachmentDownloadUrl,
  attachmentRawUrl,
  createCase,
  createExamination,
  createFollowUp,
  createPrescription,
  deleteAttachment,
  deleteCase,
  deleteExamination,
  deleteFollowUp,
  deletePrescription,
  getCase,
  getCaseStats,
  getCases,
  getCaseSummary,
  updateCase,
  updateExamination,
  updateFollowUp,
  updatePrescription,
  uploadAttachment,
} from '../api/medicalCases'

const router = useRouter()

const users = ref([])
const currentIndex = ref(0)
const cases = ref([])
const stats = ref({ total: 0, outpatient: 0, surgery: 0, allergy: 0 })
const detail = ref(null)
const activeExam = ref(null)

const view = ref('list')
const activeTab = ref('info')
const keyword = ref('')
const filterType = ref('')
const dateRange = ref(null)

const summary = ref(null)
const summaryLoading = ref(false)

const VISIT_TYPES = ['门诊', '住院', '急诊']
const NONE_CONDITION = new Set(['无', '暂无', '无病史', '无慢性病', '无慢性疾病', '无特殊', '否认', '健康', '正常', '-', 'none'])

const patient = computed(() => users.value[currentIndex.value] || null)
const patientInitial = computed(() => (patient.value?.name || '患').slice(0, 1))

const patientConditions = computed(() => {
  const raw = patient.value?.chronic_diseases || ''
  return raw
    .split(/[，,、;；·\/\s]+/)
    .map((s) => s.trim())
    .filter((s) => s && !NONE_CONDITION.has(s))
    .slice(0, 4)
})

const statCards = computed(() => [
  { key: 'total', icon: '📋', value: stats.value.total, label: '就诊次数', tone: 'blue' },
  { key: 'outpatient', icon: '🏥', value: stats.value.outpatient, label: '门诊次数', tone: 'green' },
  { key: 'surgery', icon: '🔪', value: stats.value.surgery, label: '手术次数', tone: 'purple' },
  { key: 'allergy', icon: '⚠️', value: stats.value.allergy, label: '过敏史', tone: stats.value.allergy ? 'orange' : 'blue' },
])

const typeChips = [
  { label: '全部', value: '' },
  { label: '门诊', value: '门诊' },
  { label: '住院', value: '住院' },
  { label: '急诊', value: '急诊' },
]

const visitTone = (t) => (t === '住院' ? 'orange' : t === '急诊' ? 'red' : 'blue')

const filteredCases = computed(() => {
  let list = cases.value
  const kw = keyword.value.trim()
  if (kw) {
    list = list.filter((c) =>
      [c.chief_complaint, c.hospital, c.department, c.doctor].some((f) => (f || '').includes(kw)),
    )
  }
  if (filterType.value) list = list.filter((c) => c.visit_type === filterType.value)
  if (Array.isArray(dateRange.value) && dateRange.value.length === 2) {
    const [from, to] = dateRange.value
    list = list.filter((c) => c.visit_date && c.visit_date >= from && c.visit_date <= to)
  }
  return list
})

const detailTabs = [
  { key: 'info', label: '病历信息' },
  { key: 'exams', label: '检查结果' },
  { key: 'prescriptions', label: '处方记录' },
  { key: 'followups', label: '随访记录' },
  { key: 'summary', label: 'AI摘要' },
]

const dash = (v) => (v == null || `${v}`.trim() === '' ? '未填写' : v)

const infoRows = computed(() => {
  const d = detail.value
  if (!d) return []
  return [
    { label: '主诉', value: dash(d.chief_complaint) },
    { label: '现病史', value: dash(d.present_illness) },
    { label: '既往史', value: dash(d.past_history) },
    { label: '体格检查', value: dash(d.physical_exam) },
    { label: '临床诊断', value: dash(d.diagnosis) },
    { label: '医生建议', value: dash(d.doctor_advice) },
    { label: '医生备注', value: dash(d.doctor_note) },
  ]
})

const sortedFollowUps = computed(() =>
  [...(detail.value?.follow_ups || [])].sort((a, b) => `${b.follow_date}`.localeCompare(`${a.follow_date}`)),
)

const examImageList = computed(() =>
  (activeExam.value?.attachments || []).filter((a) => a.kind === 'image').map((a) => attachmentRawUrl(a.id)),
)
const examImageIndex = (id) => {
  const imgs = (activeExam.value?.attachments || []).filter((a) => a.kind === 'image')
  return Math.max(0, imgs.findIndex((a) => a.id === id))
}
const rxImageList = (p) => (p.attachments || []).filter((a) => a.kind === 'image').map((a) => attachmentRawUrl(a.id))
const rxImageIndex = (p, id) => {
  const imgs = (p.attachments || []).filter((a) => a.kind === 'image')
  return Math.max(0, imgs.findIndex((a) => a.id === id))
}

// ---- 加载 ----
const loadUsers = async () => {
  try {
    const { data } = await getUsers()
    users.value = data || []
  } catch {
    users.value = []
  }
}

const loadCases = async () => {
  const p = patient.value
  if (!p) {
    cases.value = []
    return
  }
  try {
    const { data } = await getCases({ user_id: p.id })
    cases.value = data || []
  } catch {
    cases.value = []
  }
}

const loadStats = async () => {
  const p = patient.value
  if (!p) {
    stats.value = { total: 0, outpatient: 0, surgery: 0, allergy: 0 }
    return
  }
  try {
    const { data } = await getCaseStats(p.id)
    stats.value = data || { total: 0, outpatient: 0, surgery: 0, allergy: 0 }
  } catch {
    stats.value = { total: 0, outpatient: 0, surgery: 0, allergy: 0 }
  }
}

const reloadDetail = async () => {
  if (!detail.value) return
  try {
    const { data } = await getCase(detail.value.id)
    detail.value = data
    if (activeExam.value) {
      activeExam.value = data.examinations.find((e) => e.id === activeExam.value.id) || null
      if (!activeExam.value) view.value = 'detail'
    }
  } catch {
    ElMessage.error('加载病例详情失败')
  }
}

const switchPatient = () => {
  if (users.value.length < 2) return
  currentIndex.value = (currentIndex.value + 1) % users.value.length
  void Promise.all([loadCases(), loadStats()])
}

const goFamily = () => router.push('/family')
const backToList = () => {
  view.value = 'list'
  detail.value = null
  activeExam.value = null
  summary.value = null
}

const openDetail = async (id) => {
  try {
    const { data } = await getCase(id)
    detail.value = data
    activeTab.value = 'info'
    summary.value = null
    view.value = 'detail'
  } catch {
    ElMessage.error('加载病例详情失败')
  }
}

const openExam = (e) => {
  activeExam.value = e
  view.value = 'exam'
}

// ---- 病例表单 ----
const caseDialog = ref(false)
const editingCaseId = ref(null)
const emptyCaseForm = () => ({
  visit_date: '', visit_type: '门诊', hospital: '', department: '', doctor: '',
  chief_complaint: '', present_illness: '', past_history: '', physical_exam: '',
  diagnosis: '', doctor_advice: '', doctor_note: '', surgery_name: '',
})
const caseForm = reactive(emptyCaseForm())

const openCreateCase = () => {
  if (!patient.value) {
    ElMessage.warning('请先在健康档案中添加患者')
    return
  }
  editingCaseId.value = null
  Object.assign(caseForm, emptyCaseForm())
  caseDialog.value = true
}

const openEditCase = () => {
  if (!detail.value) return
  editingCaseId.value = detail.value.id
  Object.assign(caseForm, emptyCaseForm(), {
    visit_date: detail.value.visit_date || '',
    visit_type: detail.value.visit_type || '门诊',
    hospital: detail.value.hospital || '',
    department: detail.value.department || '',
    doctor: detail.value.doctor || '',
    chief_complaint: detail.value.chief_complaint || '',
    present_illness: detail.value.present_illness || '',
    past_history: detail.value.past_history || '',
    physical_exam: detail.value.physical_exam || '',
    diagnosis: detail.value.diagnosis || '',
    doctor_advice: detail.value.doctor_advice || '',
    doctor_note: detail.value.doctor_note || '',
    surgery_name: detail.value.surgery_name || '',
  })
  caseDialog.value = true
}

const submitCase = async () => {
  if (!caseForm.visit_date) {
    ElMessage.warning('请选择就诊日期')
    return
  }
  try {
    if (editingCaseId.value) {
      const { data } = await updateCase(editingCaseId.value, { ...caseForm })
      detail.value = data
    } else {
      await createCase({ ...caseForm, user_id: patient.value.id })
    }
    ElMessage.success('保存成功')
    caseDialog.value = false
    await Promise.all([loadCases(), loadStats()])
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  }
}

const removeCase = async () => {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm('确认删除该病例？相关检查、处方、随访与附件将一并删除。', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteCase(detail.value.id)
    ElMessage.success('已删除')
    backToList()
    await Promise.all([loadCases(), loadStats()])
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

// ---- 检查表单 ----
const examDialog = ref(false)
const editingExamId = ref(null)
const emptyExamForm = () => ({ name: '', exam_time: '', hospital: '', result: '' })
const examForm = reactive(emptyExamForm())

const openCreateExam = () => {
  editingExamId.value = null
  Object.assign(examForm, emptyExamForm())
  examDialog.value = true
}
const openEditExam = (e) => {
  editingExamId.value = e.id
  Object.assign(examForm, emptyExamForm(), {
    name: e.name || '', exam_time: e.exam_time || '', hospital: e.hospital || '', result: e.result || '',
  })
  examDialog.value = true
}
const submitExam = async () => {
  if (!examForm.name.trim()) {
    ElMessage.warning('请填写检查名称')
    return
  }
  try {
    if (editingExamId.value) {
      await updateExamination(editingExamId.value, { ...examForm })
    } else {
      await createExamination(detail.value.id, { ...examForm })
    }
    ElMessage.success('保存成功')
    examDialog.value = false
    await reloadDetail()
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  }
}
const removeExam = async (e) => {
  try {
    await ElMessageBox.confirm(`确认删除检查「${e.name}」？`, '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteExamination(e.id)
    ElMessage.success('已删除')
    await reloadDetail()
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

// ---- 处方表单 ----
const prescriptionDialog = ref(false)
const editingPrescriptionId = ref(null)
const emptyDrug = () => ({ name: '', dosage: '', usage: '', frequency: '', duration: '' })
const prescriptionForm = reactive({ issued_date: '', note: '', drugs: [emptyDrug()] })

const addDrug = () => prescriptionForm.drugs.push(emptyDrug())
const removeDrug = (i) => {
  prescriptionForm.drugs.splice(i, 1)
  if (!prescriptionForm.drugs.length) prescriptionForm.drugs.push(emptyDrug())
}

const openCreatePrescription = () => {
  editingPrescriptionId.value = null
  Object.assign(prescriptionForm, { issued_date: '', note: '', drugs: [emptyDrug()] })
  prescriptionDialog.value = true
}
const openEditPrescription = (p) => {
  editingPrescriptionId.value = p.id
  Object.assign(prescriptionForm, {
    issued_date: p.issued_date || '',
    note: p.note || '',
    drugs: p.drugs && p.drugs.length ? p.drugs.map((d) => ({ ...emptyDrug(), ...d })) : [emptyDrug()],
  })
  prescriptionDialog.value = true
}
const submitPrescription = async () => {
  const drugs = prescriptionForm.drugs
    .map((d) => ({ ...d, name: (d.name || '').trim() }))
    .filter((d) => d.name)
  if (!drugs.length) {
    ElMessage.warning('请至少填写一种药品')
    return
  }
  const payload = { issued_date: prescriptionForm.issued_date, note: prescriptionForm.note, drugs }
  try {
    if (editingPrescriptionId.value) {
      await updatePrescription(editingPrescriptionId.value, payload)
    } else {
      await createPrescription(detail.value.id, payload)
    }
    ElMessage.success('保存成功')
    prescriptionDialog.value = false
    await reloadDetail()
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  }
}
const removePrescription = async (p) => {
  try {
    await ElMessageBox.confirm('确认删除该处方？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deletePrescription(p.id)
    ElMessage.success('已删除')
    await reloadDetail()
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

// ---- 随访表单 ----
const followUpDialog = ref(false)
const editingFollowUpId = ref(null)
const emptyFollowUpForm = () => ({ follow_date: '', advice: '', recovery: '', next_plan: '', completed: false })
const followUpForm = reactive(emptyFollowUpForm())

const openCreateFollowUp = () => {
  editingFollowUpId.value = null
  Object.assign(followUpForm, emptyFollowUpForm())
  followUpDialog.value = true
}
const openEditFollowUp = (f) => {
  editingFollowUpId.value = f.id
  Object.assign(followUpForm, emptyFollowUpForm(), {
    follow_date: f.follow_date || '', advice: f.advice || '', recovery: f.recovery || '',
    next_plan: f.next_plan || '', completed: !!f.completed,
  })
  followUpDialog.value = true
}
const submitFollowUp = async () => {
  const payload = {
    follow_date: followUpForm.follow_date,
    advice: followUpForm.advice,
    recovery: followUpForm.recovery,
    next_plan: followUpForm.next_plan,
    completed: followUpForm.completed ? 1 : 0,
  }
  try {
    if (editingFollowUpId.value) {
      await updateFollowUp(editingFollowUpId.value, payload)
    } else {
      await createFollowUp(detail.value.id, payload)
    }
    ElMessage.success('保存成功')
    followUpDialog.value = false
    await reloadDetail()
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  }
}
const removeFollowUp = async (f) => {
  try {
    await ElMessageBox.confirm('确认删除该随访记录？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteFollowUp(f.id)
    ElMessage.success('已删除')
    await reloadDetail()
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

// ---- 附件上传 ----
const fileInput = ref(null)
const uploadTarget = ref({ ownerType: 'case', ownerId: null })
const triggerUpload = (ownerType, ownerId = null) => {
  uploadTarget.value = { ownerType, ownerId }
  if (fileInput.value) {
    fileInput.value.value = ''
    fileInput.value.click()
  }
}
const onFileChange = async (e) => {
  const files = Array.from(e.target.files || [])
  if (!files.length || !detail.value) return
  try {
    for (const f of files) {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('owner_type', uploadTarget.value.ownerType)
      if (uploadTarget.value.ownerId != null) fd.append('owner_id', uploadTarget.value.ownerId)
      await uploadAttachment(detail.value.id, fd)
    }
    ElMessage.success('上传成功')
    await reloadDetail()
  } catch {
    ElMessage.error('上传失败，请检查文件格式与大小')
  }
}
const removeAttachment = async (a) => {
  try {
    await ElMessageBox.confirm('确认删除该附件？', '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteAttachment(a.id)
    ElMessage.success('已删除')
    await reloadDetail()
  } catch {
    ElMessage.error('删除失败，请稍后再试')
  }
}

// ---- AI 摘要 ----
const generateSummary = async () => {
  if (!detail.value || summaryLoading.value) return
  summaryLoading.value = true
  try {
    const { data } = await getCaseSummary(detail.value.id)
    summary.value = data
  } catch (err) {
    ElMessage.error(err?.message || '生成失败，请稍后再试')
  } finally {
    summaryLoading.value = false
  }
}

onMounted(async () => {
  await loadUsers()
  await Promise.all([loadCases(), loadStats()])
})
</script>

<style scoped>
.family-records {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 16px;
}

/* 顶部栏 */
.fr-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.back-btn {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--card);
  color: var(--text);
  cursor: pointer;
}

.back-btn svg {
  width: 20px;
  height: 20px;
}

.fr-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.fr-title h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: var(--text);
}

.fr-title span {
  font-size: 13px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fr-add {
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

.fr-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

/* 卡片通用 */
.fr-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 14px;
  box-shadow: var(--shadow);
}

.fr-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.fr-card-head strong {
  font-size: 17px;
}

.head-count {
  font-size: 13px;
  color: var(--muted);
  font-weight: 600;
}

.mini-btn {
  border: 1px solid var(--primary);
  border-radius: 10px;
  padding: 6px 12px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.mini-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

.stat-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.stat-card.tone-green .stat-value { color: #16a34a; }
.stat-card.tone-orange .stat-value { color: #d97706; }
.stat-card.tone-purple .stat-value { color: #722ed1; }
.stat-card.tone-blue .stat-value { color: var(--primary); }

/* 搜索栏 */
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 14px;
  background: var(--card);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}

.search-icon {
  font-size: 16px;
}

.search-bar input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: var(--text);
}

/* 筛选行 */
.filter-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.fr-date {
  width: 100%;
}

.type-chips {
  display: flex;
  gap: 8px;
}

.type-chips button {
  flex: 1;
  padding: 7px 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.type-chips button.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

/* 病例列表 */
.case-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.case-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  padding: 12px 30px 12px 14px;
  border-radius: 14px;
  background: #f8fbff;
  border: 1px solid var(--border);
  cursor: pointer;
}

.cc-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cc-date {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
}

.cc-type {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.cc-type.vt-blue { color: var(--primary); background: var(--primary-soft); }
.cc-type.vt-orange { color: #d97706; background: #fff2e0; }
.cc-type.vt-red { color: #dc2626; background: #fef3f2; }

.cc-complaint {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.cc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--muted);
  font-size: 13px;
}

.chevron {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--muted);
  font-size: 22px;
}

/* 详情 hero */
.detail-hero {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 16px;
  color: #fff;
  background: linear-gradient(135deg, #1677ff, #4096ff);
  box-shadow: 0 8px 20px rgba(22, 119, 255, 0.22);
}

.hero-avatar {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 16px;
  font-size: 24px;
  font-weight: 800;
  background: rgba(255, 255, 255, 0.22);
  flex-shrink: 0;
}

.hero-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.hero-name {
  font-size: 19px;
  font-weight: 800;
}

.hero-meta,
.hero-diag {
  font-size: 13px;
  opacity: 0.94;
}

/* Tabs */
.detail-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
}

.detail-tabs button {
  flex: 1;
  white-space: nowrap;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.detail-tabs button.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

/* 信息行 */
.info-list {
  display: flex;
  flex-direction: column;
}

.info-row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.info-row:last-child {
  border-bottom: none;
}

.info-row.block {
  flex-direction: column;
  gap: 4px;
}

.info-label {
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.info-value {
  color: var(--text);
  font-size: 15px;
  font-weight: 600;
  white-space: pre-wrap;
  word-break: break-word;
}

.result-block {
  margin-top: 10px;
}

.block-label {
  color: var(--muted);
  font-size: 14px;
  font-weight: 600;
}

.block-text {
  margin: 6px 0 0;
  font-size: 15px;
  color: var(--text);
  white-space: pre-wrap;
}

/* 子实体卡片 */
.sub-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sub-card {
  padding: 12px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid var(--border);
}

.sub-main {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  cursor: pointer;
  padding: 0;
}

.sub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sub-head strong {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
}

.img-badge {
  font-size: 12px;
  color: var(--primary);
  font-weight: 700;
}

.sub-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}

.sub-text {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--text);
  white-space: pre-wrap;
}

.sub-ops {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.sub-ops.inline {
  margin-top: 0;
}

.sub-op {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.sub-op.del {
  color: #dc2626;
}

/* 药品表 */
.drug-table {
  width: 100%;
  margin-top: 10px;
  border-collapse: collapse;
  font-size: 13px;
}

.drug-table th,
.drug-table td {
  padding: 6px 8px;
  border: 1px solid var(--border);
  text-align: left;
}

.drug-table th {
  background: #eef4ff;
  color: var(--muted);
  font-weight: 700;
}

/* 处方图片 */
.rx-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.rx-img {
  width: 72px;
  height: 72px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.rx-add {
  width: 72px;
  height: 72px;
  border: 1px dashed var(--primary);
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

/* 附件网格 */
.attach-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 10px;
}

.attach-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.attach-img {
  width: 100%;
  height: 100px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.attach-file {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 100px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: #f8fbff;
  text-decoration: none;
  color: var(--text);
}

.file-ic {
  font-size: 28px;
}

.file-name {
  font-size: 11px;
  padding: 0 6px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.attach-actions {
  display: flex;
  justify-content: space-between;
  gap: 6px;
}

.attach-op {
  flex: 1;
  text-align: center;
  padding: 4px 0;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
}

.attach-op.del {
  color: #dc2626;
}

/* 随访时间轴 */
.fr-timeline {
  padding-top: 4px;
  padding-left: 4px;
}

.fu-card {
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fbff;
  border: 1px solid var(--border);
}

.fu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.fu-status {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.fu-status.done {
  color: #16a34a;
  background: #ecfdf3;
}

.fu-status.pending {
  color: var(--primary);
  background: var(--primary-soft);
}

.fu-row {
  margin: 4px 0 0;
  font-size: 14px;
  color: var(--text);
}

.fu-row b {
  color: var(--muted);
  font-weight: 700;
}

/* AI 摘要 */
.summary-box {
  display: flex;
  flex-direction: column;
}

.sum-row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.sum-row:last-child {
  border-bottom: none;
}

.sum-label {
  flex-shrink: 0;
  width: 76px;
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
}

.sum-value {
  flex: 1;
  font-size: 15px;
  color: var(--text);
  font-weight: 600;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.risk-tag {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  color: #b42318;
  background: #fef3f2;
}

/* 详情底部操作 */
.detail-actions {
  display: flex;
  gap: 10px;
}

.act-btn {
  flex: 1;
  padding: 11px 0;
  border-radius: 12px;
  border: none;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.act-btn.del {
  color: #dc2626;
  background: #fef3f2;
}

/* 药品编辑器 */
.drug-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.drug-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 1fr 1fr auto;
  gap: 6px;
  align-items: center;
}

.tt-del {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: #dc2626;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.tt-add {
  align-self: flex-start;
  padding: 7px 14px;
  border: 1px dashed var(--primary);
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

/* 表单通用 */
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0 12px;
}

.dlg-btn {
  padding: 9px 20px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.dlg-btn.ghost {
  border: 1px solid var(--border);
  background: #fff;
  color: var(--text);
}

.dlg-btn.primary {
  border: none;
  background: var(--primary);
  color: #fff;
  margin-left: 8px;
}
</style>
