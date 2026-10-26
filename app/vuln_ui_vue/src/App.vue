<template>
  <div class="app-root">
    <Banner :chatOpen="chatOpen" @toggle-chat="chatOpen = !chatOpen" />

    <ChatDrawer :open="chatOpen" :scanId="scanId" @close="chatOpen = false" />

    <main class="main-content">
      <!-- Intro — only shown before any scan starts -->
      <div v-if="phase === 'idle'" class="intro-card">
        <div class="intro-title">Sovereign Vulnerability Analysis</div>
        <p class="intro-body">
          Submit any public Git repository and SOVA will scan it for security vulnerabilities
          using Semgrep and Bandit — all inside a hardware-isolated Kata VM with enforced
          network egress control. Your code never leaves the cluster.
        </p>
        <div class="intro-badges">
          <span class="intro-badge">🔒 Zero data egress</span>
          <span class="intro-badge">⚡ Semgrep · 694 rules</span>
          <span class="intro-badge">🐍 Bandit · Python SAST</span>
          <span class="intro-badge">🤖 AI remediation</span>
          <span class="intro-badge">📄 Exportable report</span>
        </div>
      </div>

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
    scanResult.value = { ...result, scan_id }
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
  max-width: 1560px; /* ~30% wider: was 1200px */
  width: 100%;
  margin: 0 auto;
  padding: 2rem 3rem;
  margin-top: 2rem; /* space for owl branch overhanging banner border */
}

.intro-card {
  background: linear-gradient(135deg, rgba(0,180,255,0.04) 0%, rgba(8,12,24,0) 60%);
  border: 1px solid rgba(0,180,255,0.12);
  border-radius: 16px;
  padding: 2rem 2.5rem;
  margin-bottom: 2rem;
}
.intro-title {
  font-size: 1.4rem;
  font-weight: 700;
  color: #f1f5f9;
  margin-bottom: 0.75rem;
  background: linear-gradient(90deg, #f1f5f9 40%, #00b4ff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.intro-body {
  font-size: 0.92rem;
  color: #64748b;
  line-height: 1.7;
  max-width: 640px;
  margin-bottom: 1.25rem;
}
.intro-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.intro-badge {
  background: rgba(0,180,255,0.06);
  border: 1px solid rgba(0,180,255,0.15);
  border-radius: 100px;
  padding: 0.25rem 0.85rem;
  font-size: 0.75rem;
  color: #94a3b8;
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
