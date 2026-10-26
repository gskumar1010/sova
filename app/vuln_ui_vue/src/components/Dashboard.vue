<template>
  <div class="dashboard">
    <!-- Session trace log — collapsed by default, above results -->
    <details class="trace-section" @toggle="loadTrace">
      <summary class="trace-toggle">🔍 Session Trace Log</summary>
      <pre class="trace-log" v-if="traceLines.length">{{ traceLines.join('\n') }}</pre>
      <div v-else class="trace-empty">No trace data yet.</div>
    </details>

    <!-- On-prem callout -->
    <div class="onprem-banner">
      🔒 <strong>Data stayed on-prem</strong>
      <span class="sep">·</span>
      <span class="allowed">✓ Model endpoint</span>
      <span class="sep">·</span>
      <span class="allowed">✓ semgrep.dev</span>
      <span class="sep">·</span>
      <span class="allowed">✓ github.com</span>
      <span class="sep">·</span>
      <span class="blocked">✗ All other egress blocked</span>
    </div>

    <!-- Section header -->
    <div class="section-header">
      Scan Results
      <span v-if="scanDuration" class="duration">· {{ scanDuration }}</span>
    </div>

    <!-- Metric cards -->
    <div class="metrics-row">
      <div class="mcard risk" :style="{ '--risk-color': riskColor }">
        <div class="risk-badge">{{ riskLabel }} RISK</div>
        <div class="mval" :style="{ color: riskColor }">{{ summary.risk }}</div>
        <div class="mlbl">Risk Score</div>
      </div>
      <div class="mcard total">
        <div class="mval cyan">{{ summary.total }}</div>
        <div class="mlbl">Total</div>
      </div>
      <div class="mcard crit">
        <div class="mval red">{{ summary.severity_counts.critical }}</div>
        <div class="mlbl">Critical</div>
      </div>
      <div class="mcard high">
        <div class="mval orange">{{ summary.severity_counts.high }}</div>
        <div class="mlbl">High</div>
      </div>
      <div class="mcard med">
        <div class="mval yellow">{{ summary.severity_counts.medium }}</div>
        <div class="mlbl">Medium</div>
      </div>
      <div class="mcard low">
        <div class="mval blue">{{ summary.severity_counts.low }}</div>
        <div class="mlbl">Low</div>
      </div>
    </div>

    <!-- Charts row — pure CSS, no external library -->
    <div v-if="summary.total > 0" class="charts-row">
      <!-- Severity distribution -->
      <div class="chart-card">
        <div class="chart-title">Severity Distribution</div>
        <div class="sev-bars">
          <div v-for="s in sevRows" :key="s.label" class="sev-row">
            <span class="sev-lbl">{{ s.label }}</span>
            <div class="sev-track">
              <div class="sev-fill" :style="{ width: s.pct + '%', background: s.color }"></div>
            </div>
            <span class="sev-count" :style="{ color: s.color }">{{ s.count }}</span>
          </div>
        </div>
      </div>
      <!-- Top rules -->
      <div class="chart-card">
        <div class="chart-title">Top 5 Rules</div>
        <div class="horiz-bars">
          <div v-for="r in topRules" :key="r.rule_id" class="hbar-row">
            <div class="hbar-label">{{ r.rule_id.split('.').pop() }}</div>
            <div class="hbar-track">
              <div class="hbar-fill" :style="{ width: (r.count / maxRuleCount * 100) + '%' }"></div>
            </div>
            <span class="hbar-count">{{ r.count }}</span>
          </div>
        </div>
      </div>
      <!-- Hotspot files -->
      <div class="chart-card">
        <div class="chart-title">Hotspot Files</div>
        <div class="horiz-bars">
          <div v-for="f in hotspotFiles" :key="f.file" class="hbar-row">
            <div class="hbar-label">{{ f.file.split('/').slice(-2).join('/') }}</div>
            <div class="hbar-track">
              <div class="hbar-fill" :style="{ width: (f.count / maxFileCount * 100) + '%' }"></div>
            </div>
            <span class="hbar-count">{{ f.count }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Findings drill-down -->
    <div v-if="summary.total > 0" class="findings-section">
      <div class="section-header">
        Findings
        <select v-model="ruleFilter" class="rule-filter">
          <option value="">All rules</option>
          <option v-for="r in topRuleIds" :key="r" :value="r">{{ r }}</option>
        </select>
      </div>

      <div class="finding-count" v-if="ruleFilter">
        {{ filteredFindings.length }} finding{{ filteredFindings.length !== 1 ? 's' : '' }} for
        <code>{{ ruleFilter }}</code>
      </div>

      <div class="findings-list">
        <details v-for="f in filteredFindings.slice(0, 20)" :key="f.rule_id + f.file + f.line" class="finding">
          <summary class="finding-summary">
            <span class="sev-badge" :class="f.severity">{{ f.severity.toUpperCase() }}</span>
            <code class="rule-id">{{ f.rule_id }}</code>
            <a v-if="f.cwe_id" :href="f.cwe_url" target="_blank" class="cwe-badge" @click.stop>
              CWE-{{ f.cwe_id }} ↗
            </a>
            <span class="file-loc">{{ f.file }}:{{ f.line }}</span>
          </summary>
          <div class="finding-body">
            <div class="finding-msg">{{ f.message }}</div>
            <div class="finding-tool">via <code>{{ f.tool }}</code></div>
            <pre v-if="f.snippet" class="snippet">{{ f.snippet }}</pre>
          </div>
        </details>
      </div>
    </div>

    <!-- AI Remediation -->
    <Remediation v-if="summary.total > 0" :scanId="props.result.scan_id" />

    <!-- Actions -->
    <div class="actions-row">
      <button class="btn-primary" @click="downloadReport">📄 Download Security Report</button>
      <button class="btn-secondary" @click="downloadSarif">📥 Download SARIF</button>
      <button class="btn-secondary" @click="$emit('new-scan')">New Scan</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import Remediation from './Remediation.vue'

const props = defineProps({
  result: { type: Object, required: true }
})
defineEmits(['new-scan'])

const traceLines = ref([])
async function loadTrace() {
  const scanId = props.result?.scan_id
  if (!scanId || traceLines.value.length) return
  try {
    const r = await fetch(`/api/scan/trace/${scanId}`)
    const d = await r.json()
    traceLines.value = d.lines || []
  } catch { /* silent */ }
}

const ruleFilter = ref('')

const summary = computed(() => props.result.summary || {
  total: 0, risk: 0,
  severity_counts: { critical: 0, high: 0, medium: 0, low: 0 },
  top_rules: [], findings: []
})
const sarif = computed(() => props.result.sarif)
const findings = computed(() => summary.value.findings || [])

const scanDuration = computed(() => {
  if (props.result.duration) return props.result.duration
  return null
})

const riskColor = computed(() => {
  const r = summary.value.risk
  if (r >= 75) return '#ef4444'
  if (r >= 45) return '#f97316'
  if (r >= 20) return '#eab308'
  return '#22c55e'
})
const riskLabel = computed(() => {
  const r = summary.value.risk
  if (r >= 75) return 'CRITICAL'
  if (r >= 45) return 'HIGH'
  if (r >= 20) return 'MEDIUM'
  return 'LOW'
})

const topRuleIds = computed(() =>
  (summary.value.top_rules || []).map(r => r.rule_id)
)
const filteredFindings = computed(() =>
  ruleFilter.value
    ? findings.value.filter(f => f.rule_id === ruleFilter.value)
    : findings.value
)

// CSS-only charts — no external library
const sevRows = computed(() => {
  const sc = summary.value.severity_counts
  const max = Math.max(sc.critical, sc.high, sc.medium, sc.low, 1)
  return [
    { label: 'Critical', count: sc.critical, color: '#ef4444', pct: sc.critical / max * 100 },
    { label: 'High',     count: sc.high,     color: '#f97316', pct: sc.high     / max * 100 },
    { label: 'Medium',   count: sc.medium,   color: '#eab308', pct: sc.medium   / max * 100 },
    { label: 'Low',      count: sc.low,      color: '#3b82f6', pct: sc.low      / max * 100 },
  ]
})

const topRules = computed(() => (summary.value.top_rules || []).slice(0, 5))
const maxRuleCount = computed(() => Math.max(...topRules.value.map(r => r.count), 1))

const hotspotFiles = computed(() => {
  const counts = {}
  for (const f of findings.value) counts[f.file] = (counts[f.file] || 0) + 1
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([file, count]) => ({ file, count }))
})
const maxFileCount = computed(() => Math.max(...hotspotFiles.value.map(f => f.count), 1))

async function downloadReport() {
  const scanId = props.result?.scan_id
  if (!scanId) return
  const url = `/api/scan/report/${scanId}`
  const a = document.createElement('a')
  a.href = url
  a.download = `sova-report-${scanId.slice(0,8)}.html`
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

function downloadSarif() {
  if (!sarif.value) return
  const blob = new Blob([JSON.stringify(sarif.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'sova-report.sarif'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 100)
}
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 1.5rem; }

.onprem-banner {
  background: rgba(34,197,94,0.04);
  border: 1px solid rgba(34,197,94,0.15);
  border-left: 3px solid #22c55e;
  border-radius: 8px;
  padding: 0.65rem 1rem;
  font-size: 0.78rem;
  color: #475569;
  display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center;
}
.onprem-banner strong { color: #22c55e; }
.sep { color: #334155; }
.allowed { color: #22c55e; }
.blocked { color: #ef4444; }

.section-header {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #475569;
  display: flex; align-items: center; gap: 0.5rem;
}
.section-header::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(0,180,255,0.08);
}
.duration { color: #334155; text-transform: none; letter-spacing: 0; font-weight: 400; }

.metrics-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.mcard {
  flex: 1; min-width: 90px;
  background: rgba(8,12,24,0.7);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 1rem;
  text-align: center;
  backdrop-filter: blur(10px);
  transition: transform 0.2s;
}
.mcard:hover { transform: translateY(-2px); }
.mcard.risk { border-color: rgba(255,255,255,0.1); flex: 1.2; }
.mcard.total { border-color: rgba(0,180,255,0.2); }
.mcard.crit  { border-color: rgba(239,68,68,0.25); }
.mcard.high  { border-color: rgba(249,115,22,0.25); }
.mcard.med   { border-color: rgba(234,179,8,0.2); }
.mcard.low   { border-color: rgba(59,130,246,0.2); }

.risk-badge {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: v-bind(riskColor);
  margin-bottom: 0.2rem;
}

.mval {
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -1px;
  margin-bottom: 0.3rem;
}
.mval.cyan   { color: #00b4ff; text-shadow: 0 0 20px rgba(0,180,255,0.4); }
.mval.red    { color: #ef4444; text-shadow: 0 0 20px rgba(239,68,68,0.4); }
.mval.orange { color: #f97316; text-shadow: 0 0 20px rgba(249,115,22,0.3); }
.mval.yellow { color: #eab308; text-shadow: 0 0 20px rgba(234,179,8,0.3); }
.mval.blue   { color: #3b82f6; text-shadow: 0 0 20px rgba(59,130,246,0.3); }

.mlbl {
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #475569;
}

.charts-row {
  display: grid;
  grid-template-columns: 1fr 1.5fr 1.5fr;
  gap: 1rem;
}
.chart-card {
  background: rgba(8,12,24,0.7);
  border: 1px solid rgba(0,180,255,0.1);
  border-radius: 12px;
  padding: 1rem;
}
.chart-title {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: #475569; margin-bottom: 0.75rem;
}

/* Severity bars */
.sev-bars { display: flex; flex-direction: column; gap: 0.5rem; }
.sev-row { display: flex; align-items: center; gap: 0.5rem; }
.sev-lbl { font-size: 0.7rem; color: #64748b; width: 52px; flex-shrink: 0; }
.sev-track { flex: 1; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.sev-fill { height: 100%; border-radius: 3px; transition: width 0.6s cubic-bezier(.4,0,.2,1); }
.sev-count { font-size: 0.72rem; font-weight: 700; width: 24px; text-align: right; flex-shrink: 0; }

/* Horizontal bars */
.horiz-bars { display: flex; flex-direction: column; gap: 0.45rem; }
.hbar-row { display: flex; align-items: center; gap: 0.5rem; }
.hbar-label { font-size: 0.68rem; color: #64748b; width: 110px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbar-track { flex: 1; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.hbar-fill { height: 100%; background: rgba(0,180,255,0.55); border-radius: 3px; transition: width 0.6s cubic-bezier(.4,0,.2,1); }
.hbar-count { font-size: 0.7rem; color: #475569; width: 20px; text-align: right; flex-shrink: 0; }

.findings-section { display: flex; flex-direction: column; gap: 0.75rem; }

.rule-filter {
  background: rgba(8,12,24,0.8);
  border: 1px solid rgba(0,180,255,0.2);
  border-radius: 6px;
  color: var(--text-dim);
  padding: 0.2rem 0.5rem;
  font-size: 0.72rem;
  margin-left: 0.5rem;
}
.rule-filter option { background: #0d1117; }

.finding-count { font-size: 0.78rem; color: #475569; }
.finding-count code { color: var(--cyan); }

.findings-list { display: flex; flex-direction: column; gap: 0.4rem; }

.finding {
  background: rgba(8,12,24,0.6);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px;
  transition: border-color 0.2s;
}
.finding:hover { border-color: rgba(0,180,255,0.15); }

.finding-summary {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 1rem;
  cursor: pointer;
  font-size: 0.82rem;
  user-select: none;
  list-style: none;
}
.finding-summary::-webkit-details-marker { display: none; }

.sev-badge {
  padding: 2px 7px;
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  flex-shrink: 0;
}
.sev-badge.critical { background: rgba(239,68,68,0.15); color:#ef4444; border:1px solid rgba(239,68,68,0.3); }
.sev-badge.high     { background: rgba(249,115,22,0.12); color:#f97316; border:1px solid rgba(249,115,22,0.3); }
.sev-badge.medium   { background: rgba(234,179,8,0.10); color:#eab308; border:1px solid rgba(234,179,8,0.3); }
.sev-badge.low      { background: rgba(59,130,246,0.10); color:#3b82f6; border:1px solid rgba(59,130,246,0.3); }

.rule-id { color: var(--cyan); font-size: 0.78rem; }
.file-loc { color: #475569; font-size: 0.76rem; margin-left: auto; }

.finding-body { padding: 0.5rem 1rem 0.75rem; display: flex; flex-direction: column; gap: 0.4rem; }
.finding-msg { color: var(--text-dim); font-size: 0.82rem; }
.finding-tool { font-size: 0.72rem; color: #334155; }
.finding-tool code { color: #475569; }

.snippet {
  background: rgba(0,0,0,0.3);
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  font-size: 0.76rem;
  color: #8b949e;
  font-family: var(--mono);
  overflow-x: auto;
  white-space: pre;
}

.actions-row {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.btn-primary {
  background: var(--cyan);
  border: none;
  border-radius: 8px;
  color: #050810;
  font-weight: 700;
  padding: 0.55rem 1.25rem;
  font-size: 0.875rem;
  transition: opacity 0.2s;
}
.btn-primary:hover { opacity: 0.85; }

.btn-secondary {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  color: var(--text-dim);
  font-weight: 500;
  padding: 0.55rem 1.25rem;
  font-size: 0.875rem;
  transition: all 0.2s;
}
.btn-secondary:hover { background: rgba(255,255,255,0.08); color: var(--text); }

.cwe-badge {
  display: inline-flex; align-items: center;
  background: rgba(59,130,246,0.1);
  border: 1px solid rgba(59,130,246,0.3);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.68rem; font-weight: 600;
  color: #3b82f6;
  text-decoration: none;
  flex-shrink: 0;
  transition: background 0.15s;
}
.cwe-badge:hover { background: rgba(59,130,246,0.2); }

.trace-section {
  background: rgba(8,12,24,0.8);
  border: 1px solid rgba(0,180,255,0.1);
  border-radius: 8px;
  overflow: hidden;
}
.trace-toggle {
  padding: 0.65rem 1rem;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #475569;
  cursor: pointer;
  user-select: none;
  list-style: none;
}
.trace-toggle:hover { color: #64748b; }
.trace-log {
  margin: 0;
  padding: 0.75rem 1rem;
  font-family: var(--mono);
  font-size: 0.72rem;
  color: #475569;
  line-height: 1.6;
  white-space: pre-wrap;
  border-top: 1px solid rgba(255,255,255,0.04);
  max-height: 300px;
  overflow-y: auto;
}
.trace-empty {
  padding: 0.75rem 1rem;
  font-size: 0.78rem;
  color: #334155;
  border-top: 1px solid rgba(255,255,255,0.04);
}
</style>
