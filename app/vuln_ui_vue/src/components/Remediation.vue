<template>
  <div class="remediation">
    <div class="rem-header">
      <span class="rem-icon">🔧</span>
      <span>AI Remediation — {{ loading ? 'Analysing Critical/High Findings' : `Top ${fixes.length} Critical/High Findings` }}</span>
      <span v-if="loading" class="rem-loading">Generating fixes via nemotron-30b…</span>
    </div>

    <div v-if="loading" class="rem-pending">
      <div class="rem-dots">
        <span></span><span></span><span></span>
      </div>
      <div class="rem-hint">The AI agent is reading the code and generating patches…</div>
    </div>

    <div v-else-if="fixes.length === 0" class="rem-empty">
      No remediation available — no critical or high findings found.
    </div>

    <div v-else class="rem-list">
      <details v-for="fix in fixes" :key="fix.rule_id + fix.file" class="rem-item">
        <summary class="rem-summary">
          <span class="sev-badge" :class="fix.severity">{{ fix.severity?.toUpperCase() }}</span>
          <code class="rem-rule">{{ fix.rule_id }}</code>
          <a v-if="fix.cwe_id" :href="`https://cwe.mitre.org/data/definitions/${fix.cwe_id}.html`"
             target="_blank" class="cwe-badge" @click.stop>CWE-{{ fix.cwe_id }} ↗</a>
          <span class="rem-loc">{{ fix.file?.split('/').pop() }}:{{ fix.line }}</span>
        </summary>
        <div class="rem-body">
          <div class="rem-msg">{{ fix.message }}</div>
          <div class="rem-fix" v-html="renderFix(fix.fix_text)"></div>
        </div>
      </details>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({ scanId: String })
const fixes = ref([])
const loading = ref(true)
let pollTimer = null

async function poll() {
  if (!props.scanId) return
  try {
    const r = await fetch(`/api/scan/remediation/${props.scanId}`)
    const d = await r.json()
    if (d.status === 'done') {
      fixes.value = d.fixes || []
      loading.value = false
      clearInterval(pollTimer)
    }
  } catch { /* silent */ }
}

onMounted(() => {
  poll()
  pollTimer = setInterval(poll, 5000)
})
onBeforeUnmount(() => clearInterval(pollTimer))

function renderFix(text) {
  if (!text) return ''
  // Convert markdown code blocks to styled HTML
  return text
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre class="code-block"><code>${code.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</code></pre>`)
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
.remediation {
  background: rgba(8,12,24,0.8);
  border: 1px solid rgba(0,180,255,0.15);
  border-radius: 12px;
  overflow: hidden;
}
.rem-header {
  display: flex; align-items: center; gap: 0.6rem;
  background: linear-gradient(90deg,rgba(0,180,255,0.09),rgba(0,180,255,0.03));
  border-bottom: 1px solid rgba(0,180,255,0.12);
  padding: 0.75rem 1rem;
  font-size: 0.78rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: #475569;
}
.rem-icon { font-size: 1rem; }
.rem-loading { margin-left: auto; font-size: 0.72rem; color: #334155; font-weight: 400; text-transform: none; letter-spacing: 0; }
.rem-pending { padding: 2rem; text-align: center; }
.rem-dots { display: flex; justify-content: center; gap: 5px; margin-bottom: 0.75rem; }
.rem-dots span { width: 8px; height: 8px; border-radius: 50%; background: #00b4ff; animation: bounce 1.2s infinite; }
.rem-dots span:nth-child(2) { animation-delay: 0.2s; }
.rem-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce { 0%,60%,100% { transform:translateY(0);opacity:.5; } 30% { transform:translateY(-6px);opacity:1; } }
.rem-hint { font-size: 0.78rem; color: #334155; }
.rem-empty { padding: 1.5rem; text-align: center; font-size: 0.82rem; color: #334155; }
.rem-list { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem; }
.rem-item {
  background: rgba(5,8,16,0.6);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 8px; overflow: hidden;
}
.rem-item:hover { border-color: rgba(0,180,255,0.15); }
.rem-summary {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.6rem 0.85rem; cursor: pointer;
  list-style: none; flex-wrap: wrap;
}
.rem-rule { font-size: 0.8rem; color: #00b4ff; }
.rem-loc { font-size: 0.72rem; color: #475569; margin-left: auto; }
.rem-body { padding: 0.75rem 1rem; border-top: 1px solid rgba(255,255,255,0.04); }
.rem-msg { font-size: 0.8rem; color: #64748b; margin-bottom: 0.75rem; }
.rem-fix { font-size: 0.82rem; color: #cbd5e1; line-height: 1.6; }

.sev-badge {
  padding: 2px 8px; border-radius: 4px;
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; flex-shrink: 0;
}
.sev-badge.critical { background: rgba(239,68,68,0.15); color:#ef4444; border:1px solid rgba(239,68,68,.3); }
.sev-badge.high { background: rgba(249,115,22,0.12); color:#f97316; border:1px solid rgba(249,115,22,.3); }
.sev-badge.medium { background: rgba(234,179,8,0.1); color:#eab308; border:1px solid rgba(234,179,8,.3); }
.sev-badge.low { background: rgba(59,130,246,0.1); color:#3b82f6; border:1px solid rgba(59,130,246,.3); }
.cwe-badge {
  display:inline-flex;align-items:center;background:rgba(59,130,246,.1);
  border:1px solid rgba(59,130,246,.3);border-radius:4px;padding:1px 6px;
  font-size:.68rem;font-weight:600;color:#3b82f6;text-decoration:none;flex-shrink:0;
}
.cwe-badge:hover { background:rgba(59,130,246,.2); }
:deep(.code-block) {
  background: #0d1117; border: 1px solid #1e293b; border-radius: 6px;
  padding: 0.75rem; margin: 0.5rem 0; overflow-x: auto;
  font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;
  color: #94a3b8; white-space: pre;
}
</style>
