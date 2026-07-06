<template>
  <section class="compact-page">
    <div class="compact-page__head">
      <h1>语音状态</h1>
      <el-tag :type="statusTagType">{{ statusLabel }}</el-tag>
    </div>
    <div class="compact-page__body device-grid">
      <div class="card section-card">
        <strong class="block-title">连接状态</strong>
        <div class="meta-list">
          <div><span>在线</span><strong>{{ status.online ? '是' : '否' }}</strong></div>
          <div><span>TTS</span><strong>{{ ttsLabel }}</strong></div>
          <div><span>播报中</span><strong>{{ status.tts_playing ?? status.tts_busy ? '是' : '否' }}</strong></div>
        </div>
        <p class="hint">日常使用请在首页说「小医」唤醒，无需在此开启其他语音模式。</p>
        <el-button type="primary" @click="refreshStatus">刷新</el-button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getDeviceStatus } from '../api/device'

const status = ref({ online: false, tts_enabled: null, error: '' })

const statusLabel = computed(() => (status.value.online ? '在线' : '离线'))
const statusTagType = computed(() => (status.value.online ? 'success' : 'warning'))
const ttsLabel = computed(() => {
  if (status.value.tts_enabled === null) return '-'
  return status.value.tts_enabled ? '可用' : '静音'
})

const refreshStatus = async () => {
  try {
    const { data } = await getDeviceStatus()
    status.value = data
  } catch {
    ElMessage.error('无法获取设备状态')
  }
}

onMounted(refreshStatus)
</script>

<style scoped>
.device-grid {
  display: grid;
  gap: 8px;
}

.section-card {
  padding: 12px;
}

.block-title {
  display: block;
  margin-bottom: 10px;
  font-size: 18px;
}

.meta-list {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}

.meta-list div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.meta-list span {
  color: var(--muted);
}

.hint {
  margin: 0 0 12px;
  color: var(--muted);
  line-height: 1.5;
}
</style>
