<template>
  <div class="app-root">
    <Banner :chatOpen="chatOpen" @toggle-chat="chatOpen = !chatOpen" />

    <ChatDrawer :open="chatOpen" :scanId="scanId" @close="chatOpen = false" />

    <main class="main-content">
      <ScanInput
        v-if="phase === 'idle'"
        @start-scan="handleScanStart"
      />

      <Pipeline
        v-if="phase === 'scanning'"
        :events="progressEvents"
        :logLines="logLines"
      />

      <Dashboard
        v-if="phase === 'done' && scanResult"
        :result="scanResult"
        @new-scan="resetScan"
      />

      <div v-if="phase === 'error'" class="error-panel">
        <div class="error-title">Scan Failed</div>
        <div class="error-msg">{{ errorMsg }}</div>
        <button class="btn-primary" @click="resetScan">Try Again</button>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import Banner from './components/Banner.vue'
import ChatDrawer from './components/ChatDrawer.vue'
import ScanInput from './components/ScanInput.vue'
import Pipeline from './components/Pipeline.vue'
import Dashboard from './components/Dashboard.vue'
import { startScan, streamScan, getResult } from './api.js'

const chatOpen = ref(false)
const phase = ref('idle')   // idle | scanning | done | error
const scanId = ref(null)
const scanResult = ref(null)
const errorMsg = ref('')
const progressEvents = ref([])
const logLines = ref([])

async function handleScanStart(gitUrl) {
  phase.value = 'scanning'
  progressEvents.value = []
  logLines.value = []
  scanResult.value = null
  scanId.value = null

  logLines.value.push({ ts: now(), text: 'Scan initiated — connecting to Kata VM sandbox' })

  try {
    const { scan_id } = await startScan(gitUrl)
    scanId.value = scan_id

    const es = streamScan(scan_id)
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      if (ev.step === 'done') {
        es.close()
        fetchResult(scan_id)
        return
      }
      progressEvents.value = [...progressEvents.value, ev]
      const icon = ev.status === 'completed' ? '✓' : ev.status === 'failed' ? '✗' : '→'
      const detail = ev.detail ? ` (${ev.detail})` : ''
      logLines.value.push({ ts: now(), text: `${icon} ${ev.step} ${ev.status}${detail}` })
    }
    es.onerror = () => {
      es.close()
      fetchResult(scan_id)
    }
  } catch (err) {
    phase.value = 'error'
    errorMsg.value = err.message || 'Failed to start scan'
  }
}

async function fetchResult(scan_id) {
  try {
    const result = await getResult(scan_id)
    scanResult.value = result
    phase.value = 'done'
    logLines.value.push({ ts: now(), text: `✓ Scan complete — ${result.summary?.total || 0} findings` })
  } catch (err) {
    phase.value = 'error'
    errorMsg.value = err.message || 'Failed to retrieve results'
  }
}

function resetScan() {
  phase.value = 'idle'
  scanResult.value = null
  progressEvents.value = []
  logLines.value = []
  scanId.value = null
}

function now() {
  const d = new Date()
  const m = String(d.getMinutes()).padStart(2,'0')
  const s = String(d.getSeconds()).padStart(2,'0')
  return `[${m}:${s}]`
}
</script>

<style scoped>
.app-root {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.main-content {
  flex: 1;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 2rem;
  margin-top: 2rem; /* space for owl branch overhanging banner border */
}

.error-panel {
  background: rgba(239,68,68,0.06);
  border: 1px solid rgba(239,68,68,0.3);
  border-left: 3px solid #ef4444;
  border-radius: 8px;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.error-title { font-weight: 700; color: #f87171; font-size: 1rem; }
.error-msg { color: #8b949e; font-size: 0.875rem; font-family: var(--mono); }

.btn-primary {
  background: var(--cyan);
  border: none;
  border-radius: 8px;
  color: #050810;
  font-weight: 700;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  align-self: flex-start;
  transition: opacity 0.2s;
}
.btn-primary:hover { opacity: 0.85; }
</style>
