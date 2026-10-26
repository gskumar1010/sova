<template>
  <div class="pipeline-wrap">
    <div class="pipeline">
      <template v-for="(step, i) in STEPS" :key="step.key">
        <div class="step" :class="stepClass(step.key)">
          <div class="step-icon">
            <span v-if="stepStatus(step.key) === 'completed'">✓</span>
            <span v-else-if="stepStatus(step.key) === 'failed'">✗</span>
            <span v-else-if="stepStatus(step.key) === 'started'" class="spinner">⟳</span>
            <span v-else>{{ step.icon }}</span>
          </div>
          <div class="step-label">{{ step.label }}</div>
          <div class="step-detail">
            <template v-if="stepStatus(step.key) === 'started'">
              <div class="pct">{{ pct(step.key) }}%</div>
              <div class="pct-bar">
                <div class="pct-fill" :style="{ width: pct(step.key) + '%' }"></div>
              </div>
            </template>
            <div v-else-if="stepDetail(step.key)" class="detail-text">{{ stepDetail(step.key) }}</div>
          </div>
        </div>
        <div v-if="i < STEPS.length - 1" class="connector" :class="connectorClass(step.key)"></div>
      </template>
    </div>

    <div class="log-panel" ref="logEl">
      <div v-for="(line, i) in logLines" :key="i" class="log-line">
        <span class="log-ts">{{ line.ts }}</span>
        <span>{{ line.text }}</span>
      </div>
      <span class="elapsed-timer">{{ elapsed }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  events: { type: Array, default: () => [] },
  logLines: { type: Array, default: () => [] },
})

const STEPS = [
  { key: 'clone',    label: 'Clone',       icon: '📦', est: 60 },
  { key: 'semgrep',  label: 'Semgrep',     icon: '🔍', est: 180 },
  { key: 'bandit',   label: 'Bandit',      icon: '🐍', est: 60 },
  { key: 'analysis', label: 'AI Analysis', icon: '🤖', est: 90 },
]

const startTimes = ref({})
const elapsed = ref('00:00')
let timer = null

onMounted(() => {
  startTimes.value['clone'] = Date.now()
  timer = setInterval(() => {
    const t = Math.floor((Date.now() - (startTimes.value['clone'] || Date.now())) / 1000)
    const m = String(Math.floor(t/60)).padStart(2,'0')
    const s = String(t%60).padStart(2,'0')
    elapsed.value = `${m}:${s}`
  }, 1000)
})
onUnmounted(() => clearInterval(timer))

function latestEvent(stepKey) {
  return [...props.events].reverse().find(e => e.step === stepKey) || null
}

function stepStatus(stepKey) {
  const ev = latestEvent(stepKey)
  if (!ev) return 'pending'
  return ev.status // started | completed | failed
}

function stepDetail(stepKey) {
  const ev = latestEvent(stepKey)
  return ev?.detail || ''
}

function stepClass(stepKey) {
  const s = stepStatus(stepKey)
  // Determine active: started but not completed/failed
  return {
    pending: s === 'pending',
    active: s === 'started',
    done: s === 'completed',
    failed: s === 'failed',
  }
}

function connectorClass(stepKey) {
  const s = stepStatus(stepKey)
  return { done: s === 'completed', active: s === 'started' }
}

function pct(stepKey) {
  const ev = latestEvent(stepKey)
  if (!ev || ev.status !== 'started') return 0
  if (!startTimes.value[stepKey]) startTimes.value[stepKey] = Date.now()
  const step = STEPS.find(s => s.key === stepKey)
  const elapsed = (Date.now() - startTimes.value[stepKey]) / 1000
  // Asymptotic curve: pct = 90 * t / (t + est)
  return Math.min(95, Math.round(90 * elapsed / (elapsed + (step?.est || 60))))
}

// Track start times from events
import { watch, nextTick } from 'vue'
watch(() => props.events, (evs) => {
  for (const ev of evs) {
    if (ev.status === 'started' && !startTimes.value[ev.step]) {
      startTimes.value[ev.step] = Date.now()
    }
  }
}, { deep: true })

// Auto-scroll log to bottom when new lines arrive
watch(() => props.logLines.length, () => {
  nextTick(() => {
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  })
})
</script>

<style scoped>
.pipeline-wrap {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.pipeline {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 1.25rem 0;
  overflow-x: auto;
}

.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  min-width: 110px;
  flex-shrink: 0;
}

.step-icon {
  width: 48px; height: 48px;
  border-radius: 50%;
  border: 2px solid #1e293b;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem;
  background: #0d1521;
  transition: all 0.3s;
}

.step-label {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #334155;
  text-align: center;
  transition: color 0.3s;
}

.step-detail { min-height: 1.4rem; text-align: center; width: 90px; }
.detail-text { font-size: 0.62rem; color: #475569; font-family: var(--mono); word-break: break-all; }
.pct { font-size: 0.72rem; color: var(--cyan); font-weight: 600; font-family: var(--mono); }
.pct-bar {
  width: 70px; height: 2px;
  background: #1e293b;
  border-radius: 1px;
  margin: 2px auto 0;
}
.pct-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--cyan), #0060aa);
  border-radius: 1px;
  transition: width 0.8s ease;
}

/* States */
.step.active .step-icon {
  border-color: var(--cyan);
  box-shadow: 0 0 0 4px rgba(0,180,255,0.12), 0 0 20px rgba(0,180,255,0.2);
}
.step.active .step-label { color: var(--cyan); }
.step.done .step-icon {
  border-color: #22c55e;
  background: rgba(34,197,94,0.08);
  box-shadow: 0 0 12px rgba(34,197,94,0.2);
}
.step.done .step-label { color: #22c55e; }
.step.failed .step-icon { border-color: #ef4444; }
.step.failed .step-label { color: #ef4444; }

.spinner {
  display: inline-block;
  animation: spin 1s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.connector {
  flex: 1;
  height: 2px;
  background: #1e293b;
  min-width: 20px;
  margin-bottom: 1.8rem;
  transition: background 0.4s;
}
.connector.done { background: linear-gradient(90deg, #22c55e, rgba(0,180,255,0.4)); }
.connector.active { background: linear-gradient(90deg, #22c55e, var(--cyan)); }

/* Log panel */
.log-panel {
  background: rgba(8,12,24,0.8);
  border: 1px solid rgba(0,180,255,0.1);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  font-family: var(--mono);
  font-size: 0.72rem;
  color: #475569;
  max-height: 220px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  scroll-behavior: smooth;
}
.log-panel::-webkit-scrollbar { width: 4px; }
.log-panel::-webkit-scrollbar-track { background: transparent; }
.log-panel::-webkit-scrollbar-thumb { background: rgba(0,180,255,0.2); border-radius: 2px; }
.log-line { display: flex; gap: 0.6rem; }
.log-ts { color: #334155; flex-shrink: 0; }
.elapsed-timer { color: #eab308; font-size: 0.82rem; font-weight: 700; letter-spacing: 0.03em; }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
</style>
