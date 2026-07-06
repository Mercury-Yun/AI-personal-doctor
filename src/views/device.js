import request from './request'

export const getDeviceStatus = () => request.get('/device/status', { timeout: 20000 })

export const getWakeInfo = () => request.get('/device/wake/info', { timeout: 20000 })

export const wakeSession = (config = {}) =>
  request.post('/device/wake/session', {}, { timeout: 32000, ...config })

export const cancelWakeSession = () => request.post('/device/wake/cancel', {})

export const pauseWakeListening = (seconds = 120, interrupt = true) =>
  request.post('/device/wake/pause', { seconds, interrupt }, { timeout: 15000 })

export const resumeWakeListening = () =>
  request.post('/device/wake/resume', {}, { timeout: 15000 })

export const listenVoice = (prompt = false, speakFirst = '') =>
  request.post('/device/listen', { prompt, speak_first: speakFirst }, { timeout: 90000 })

export const classifyIntent = (text) => request.post('/device/intent/classify', { text }, { timeout: 30000 })

export const classifyPhotoSessionAction = (text, hasPhoto = false) =>
  request.post('/device/intent/photo-session', { text, has_photo: hasPhoto }, { timeout: 30000 })

export const speakText = (text, wait = false) =>
  request.post('/device/speak', { text, wait }, { timeout: wait ? 180000 : 60000 })

export const stopActiveSpeech = () => request.post('/device/speak/stop', {}, { timeout: 10000 })

export const startVoiceMode = () => request.post('/device/voice/start')

export const stopVoiceMode = () => request.post('/device/voice/stop')

export const getTodayReminders = () => request.get('/device/reminders/today')

export const getPendingReminders = (userId) =>
  request.get('/device/reminders/pending', {
    params: userId ? { user_id: userId } : {},
    timeout: 15000,
  })

export const ackReminder = (medicationId, takeTime) =>
  request.post('/device/reminders/ack', { medication_id: medicationId, take_time: takeTime })

export const pauseReminderTts = (seconds = 90) =>
  request.post('/device/reminders/pause-tts', { seconds }, { timeout: 15000 })

export const getReminderSettings = () => request.get('/device/reminders/settings', { timeout: 10000 })

export const nudgeReminder = () => request.post('/device/reminders/nudge', {}, { timeout: 180000 })

export const speakReminderNow = () =>
  request.post('/device/reminders/speak-now', {}, { timeout: 180000 })

export const resumeReminderTts = () =>
  request.post('/device/reminders/resume-tts', {}, { timeout: 10000 })

export const capturePhoto = (config = {}) =>
  request.post('/device/camera/capture', {}, { timeout: 50000, ...config })

export const getCameraPreviewUrl = () => `/api/device/camera/last/image?t=${Date.now()}`
