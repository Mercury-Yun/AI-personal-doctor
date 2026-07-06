import request from './request'

export const getGarminStatus = () => request.get('/garmin/status')
export const getGarminOverview = (params) => request.get('/garmin/overview', { params })
export const getGarminHistory = (days = 7) => request.get('/garmin/history', { params: { days } })
