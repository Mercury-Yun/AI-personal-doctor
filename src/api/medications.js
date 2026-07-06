import request from './request'

export const getMedications = (params = {}) => request.get('/medications', { params })
export const createMedication = (data) => request.post('/medications', data)
export const updateMedication = (id, data) => request.put(`/medications/${id}`, data)
export const deleteMedication = (id) => request.delete(`/medications/${id}`)
