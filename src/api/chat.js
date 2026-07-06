import request from './request'

const parseSseEvents = (chunk, onEvent) => {
  const blocks = chunk.split('\n\n')
  blocks.slice(0, -1).forEach((block) => {
    const line = block
      .split('\n')
      .find((item) => item.startsWith('data: '))
    if (!line) return
    onEvent(JSON.parse(line.slice(6)))
  })
  return blocks[blocks.length - 1] || ''
}

export const streamChatMessage = async (payload, handlers = {}) =>
  streamChat('/api/chat/stream', payload, handlers)

export const streamVisionChatMessage = async (payload, handlers = {}, options = {}) =>
  streamChat('/api/chat/vision/stream', payload, handlers, options)

async function streamChat(url, payload, handlers = {}, options = {}) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal: options.signal,
  })

  if (!response.ok) {
    let detail = 'AI医生回复失败'
    try {
      const data = await response.json()
      detail = data.detail || detail
    } catch {
      // ignore parse errors
    }
    throw new Error(detail)
  }

  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('浏览器不支持流式回复')
  }

  const decoder = new TextDecoder()
  let buffer = ''
  let finalData = null

  while (true) {
    if (options.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = parseSseEvents(buffer, (event) => {
      if (event.type === 'meta') {
        handlers.onMeta?.(event)
      } else if (event.type === 'delta') {
        handlers.onDelta?.(event.text || '')
      } else if (event.type === 'done') {
        finalData = event
        handlers.onDone?.(event)
      } else if (event.type === 'error') {
        throw new Error(event.detail || 'AI医生回复失败')
      }
    })
  }

  if (buffer.trim()) {
    parseSseEvents(`${buffer}\n\n`, (event) => {
      if (event.type === 'done') {
        finalData = event
        handlers.onDone?.(event)
      } else if (event.type === 'error') {
        throw new Error(event.detail || 'AI医生回复失败')
      }
    })
  }

  return finalData
}

export const sendChatMessage = (data) => request.post('/chat', data, { timeout: 180000 })
export const identifyMedicine = (data = {}, config = {}) =>
  request.post('/medicine/identify', data, { timeout: 120000, ...config })
export const sendVoiceChat = (data) => request.post('/chat/voice', data, { timeout: 180000 })
export const getChatSessions = (userId) => request.get(`/chat/sessions/${userId}`)
export const createChatSession = (data) => request.post('/chat/session', data)
export const updateChatSession = (sessionId, data) => request.put(`/chat/session/${sessionId}`, data)
export const deleteChatSession = (sessionId) => request.delete(`/chat/session/${sessionId}`)
export const getChatHistory = (sessionId) => request.get(`/chat/history/${sessionId}`)
export const getRecentChats = (params = {}) => request.get('/chat/recent', { params })
export const searchKnowledge = (data) => request.post('/search_knowledge', data)
