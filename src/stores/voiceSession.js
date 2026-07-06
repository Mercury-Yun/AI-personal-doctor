import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useVoiceSessionStore = defineStore('voiceSession', () => {
  const busyType = ref(null) // 'doctor' | 'photo' | null

  function setBusy(type) {
    busyType.value = type
  }

  function clearBusy() {
    busyType.value = null
  }

  return {
    busyType,
    setBusy,
    clearBusy
  }
})
