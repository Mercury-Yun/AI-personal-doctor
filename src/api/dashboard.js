import request from './request'

export const getDashboardStats = () => request.get('/dashboard/stats')
export const getHealthProfileInsight = (userId) => request.get(`/health-profile/${userId}`)
