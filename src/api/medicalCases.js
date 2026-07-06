import request from './request'

// ---- 病例 ----
export const getCases = (params = {}) => request.get('/medical_cases', { params })
export const getCaseStats = (userId) => request.get('/medical_cases/stats', { params: { user_id: userId } })
export const getCase = (id) => request.get(`/medical_cases/${id}`)
export const createCase = (data) => request.post('/medical_cases', data)
export const updateCase = (id, data) => request.put(`/medical_cases/${id}`, data)
export const deleteCase = (id) => request.delete(`/medical_cases/${id}`)

// ---- 检查 ----
export const createExamination = (caseId, data) => request.post(`/medical_cases/${caseId}/examinations`, data)
export const updateExamination = (examId, data) => request.put(`/medical_cases/examinations/${examId}`, data)
export const deleteExamination = (examId) => request.delete(`/medical_cases/examinations/${examId}`)

// ---- 处方 ----
export const createPrescription = (caseId, data) => request.post(`/medical_cases/${caseId}/prescriptions`, data)
export const updatePrescription = (prescriptionId, data) => request.put(`/medical_cases/prescriptions/${prescriptionId}`, data)
export const deletePrescription = (prescriptionId) => request.delete(`/medical_cases/prescriptions/${prescriptionId}`)

// ---- 随访 ----
export const createFollowUp = (caseId, data) => request.post(`/medical_cases/${caseId}/follow_ups`, data)
export const updateFollowUp = (followupId, data) => request.put(`/medical_cases/follow_ups/${followupId}`, data)
export const deleteFollowUp = (followupId) => request.delete(`/medical_cases/follow_ups/${followupId}`)

// ---- 附件（仅保存/展示/下载，不做 OCR）----
export const uploadAttachment = (caseId, formData) =>
  request.post(`/medical_cases/${caseId}/attachments`, formData)
export const deleteAttachment = (attachmentId) => request.delete(`/medical_cases/attachments/${attachmentId}`)
export const attachmentRawUrl = (attachmentId) => `/api/medical_cases/attachments/${attachmentId}/raw`
export const attachmentDownloadUrl = (attachmentId) => `/api/medical_cases/attachments/${attachmentId}/download`

// ---- AI 病例摘要（实时生成，不落库）----
export const getCaseSummary = (id) => request.post(`/medical_cases/${id}/summary`)
