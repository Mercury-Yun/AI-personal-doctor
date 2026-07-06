import { defineStore } from 'pinia'
import { isMobileView } from '../utils/mobileView'

const STORAGE_KEY = 'app_mode'
const VALID = new Set(['elder', 'family'])

function readStoredMode() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return VALID.has(v) ? v : null
  } catch {
    return null
  }
}

function inferMode() {
  // 窄屏（手机）默认家属端，宽屏（板载触屏）默认老人端
  return isMobileView() ? 'family' : 'elder'
}

export const useModeStore = defineStore('mode', {
  state: () => ({
    mode: readStoredMode() || inferMode(),
  }),
  getters: {
    isElder: (s) => s.mode === 'elder',
    isFamily: (s) => s.mode === 'family',
  },
  actions: {
    setMode(mode) {
      if (!VALID.has(mode)) return
      this.mode = mode
      try {
        localStorage.setItem(STORAGE_KEY, mode)
      } catch {
        /* ignore */
      }
    },
    toggle() {
      this.setMode(this.mode === 'elder' ? 'family' : 'elder')
    },
  },
})
