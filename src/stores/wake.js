import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export const useWakeStore = defineStore('wake', () => {
  const enabled = ref(localStorage.getItem('wake_enabled') !== '0')
  const available = ref(null)
  const word = ref('小医')
  const phase = ref('off')
  const error = ref('')
  const handoff = ref(null)

  const listening = computed(() => phase.value === 'listening')
  const sessionInFlight = computed(() => phase.value === 'listening' || phase.value === 'handling')

  function setEnabled(value) {
    enabled.value = value
    localStorage.setItem('wake_enabled', value ? '1' : '0')
    if (!value) phase.value = 'off'
  }

  function setAvailable(value) {
    available.value = value
  }

  function setWord(value) {
    word.value = value || '小医'
  }

  function setPhase(value) {
    phase.value = value
  }

  function setError(value) {
    error.value = value || ''
  }

  function setHandoff(payload) {
    handoff.value = payload
  }

  function clearHandoff() {
    handoff.value = null
  }

  function toggle() {
    setEnabled(!enabled.value)
  }

  return {
    enabled,
    available,
    word,
    phase,
    error,
    handoff,
    listening,
    sessionInFlight,
    setEnabled,
    setAvailable,
    setWord,
    setPhase,
    setError,
    setHandoff,
    clearHandoff,
    toggle,
  }
})
