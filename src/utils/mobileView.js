export const MOBILE_MAX_WIDTH = 768

/** 手机远程管理页：不展示语音/问诊/问药相关界面 */
export const MOBILE_HIDDEN_ROUTES = new Set(['/doctor-chat', '/photo-medicine', '/device'])

export function isMobileView() {
  if (typeof window === 'undefined') return false
  return window.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`).matches
}

export function bindMobileView(callback) {
  if (typeof window === 'undefined') return () => {}
  const mq = window.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`)
  const handler = () => callback(mq.matches)
  mq.addEventListener('change', handler)
  return () => mq.removeEventListener('change', handler)
}
