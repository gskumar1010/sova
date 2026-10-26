<template>
  <div class="scan-wrap">
    <label class="label">Select a demo repo or paste your own URL</label>

    <!-- Searchable repo picker -->
    <div class="picker-wrap">
      <input v-model="search" class="picker-search" placeholder="🔍  Search repos…" @focus="open=true" />
      <div v-if="open && filtered.length" class="picker-drop">
        <div
          v-for="repo in filtered" :key="repo.url"
          class="picker-item" :class="{ selected: selectedDemo===repo.url }"
          @mousedown.prevent="pick(repo)"
        >
          <span class="picker-label">{{ repo.label }}</span>
          <span class="picker-tag" :class="repo.severity">{{ repo.severity }}</span>
        </div>
      </div>
      <div v-if="selectedDemo" class="picker-chosen">
        <span>✓ {{ DEMO_REPOS.find(r=>r.url===selectedDemo)?.label }}</span>
        <button class="picker-clear" @click="clear">✕</button>
      </div>
    </div>

    <div class="url-row">
      <input
        v-model="customUrl"
        type="text"
        placeholder="https://github.com/org/repo.git  (or select above)"
        class="url-input"
        :disabled="!!selectedDemo"
        @keydown.enter="startScan"
        @focus="open=false"
      />
      <button class="scan-btn" @click="startScan" :disabled="!effectiveUrl">
        Scan →
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const emit = defineEmits(['start-scan'])

const DEMO_REPOS = [
  // Supply chain / malware
  { label: '💣 Devastator — Supply chain attack demo',     url: 'https://github.com/pkredhat/devastator.git',           severity: 'critical' },
  // Python
  { label: '🐍 PyGoat — Vulnerable Django app',            url: 'https://github.com/adeyosemanputra/pygoat.git',        severity: 'high' },
  { label: '🌶️ VulnHub Flask — SQLi, XSS, CSRF',           url: 'https://github.com/signalsciences/vuln-flask-app.git', severity: 'high' },
  { label: '🔐 Django Piston — insecure API',              url: 'https://github.com/toastdriven/django-piston.git',     severity: 'medium' },
  // Terraform / Cloud
  { label: '☁️ TerraGoat — Terraform misconfigs',           url: 'https://github.com/bridgecrewio/terragoat.git',       severity: 'high' },
  { label: '🏗️ CfnGoat — CloudFormation misconfigs',        url: 'https://github.com/bridgecrewio/cfngoat.git',         severity: 'high' },
  { label: '🐳 KubeGoat — Kubernetes misconfigs',           url: 'https://github.com/madhuakula/kubernetes-goat.git',   severity: 'high' },
  // JavaScript / Node
  { label: '🧃 Juice Shop — OWASP Node.js app',             url: 'https://github.com/juice-shop/juice-shop.git',       severity: 'high' },
  { label: '🕸️ NodeGoat — OWASP Node.js',                   url: 'https://github.com/OWASP/NodeGoat.git',              severity: 'high' },
  { label: '🌐 WebGoat — Java OWASP training app',          url: 'https://github.com/WebGoat/WebGoat.git',             severity: 'high' },
  { label: '🔑 WebGoat Legacy — older Java vulns',          url: 'https://github.com/WebGoat/WebGoat-Legacy.git',      severity: 'high' },
  // PHP
  { label: '🌍 DVWA — Damn Vulnerable Web App',             url: 'https://github.com/digininja/DVWA.git',              severity: 'critical' },
  { label: '💉 bWAPP — Buggy Web App',                      url: 'https://github.com/satoru-takeuchi/bwapp.git',       severity: 'high' },
  // Multi-language
  { label: '🐉 VulnHub — Various CVE PoCs',                 url: 'https://github.com/vulhub/vulhub.git',               severity: 'critical' },
  { label: '🧪 SecurityShepherd — OWASP training',          url: 'https://github.com/OWASP/SecurityShepherd.git',      severity: 'medium' },
  // Secrets / credentials
  { label: '🔓 truffleHog test — leaked secrets',           url: 'https://github.com/trufflesecurity/test_keys.git',   severity: 'critical' },
  { label: '🗝️ git-secrets test repos',                     url: 'https://github.com/awslabs/git-secrets.git',         severity: 'medium' },
  // Container
  { label: '📦 Vulnerable Node Docker app',                 url: 'https://github.com/appsecco/dvna.git',               severity: 'high' },
  { label: '🐋 Damn Vulnerable NodeJS App',                 url: 'https://github.com/nicowillis/dvna.git',             severity: 'high' },
  // Real frameworks with known issues
  { label: '🍶 Flask — Python web framework',               url: 'https://github.com/pallets/flask.git',               severity: 'low' },
  { label: '🐘 Django — Python web framework',              url: 'https://github.com/django/django.git',               severity: 'low' },
  // Ruby
  { label: '💎 RailsGoat — OWASP Ruby on Rails',            url: 'https://github.com/OWASP/railsgoat.git',            severity: 'high' },
  // API / REST
  { label: '🔌 crAPI — Completely Ridiculous API',          url: 'https://github.com/OWASP/crAPI.git',                severity: 'high' },
  // Dependency confusion / supply chain
  { label: '📋 Safety-db — CVE dependency list',            url: 'https://github.com/pyupio/safety-db.git',           severity: 'medium' },
  // Android
  { label: '📱 InsecureBankv2 — Android vulns',             url: 'https://github.com/dineshshetty/Android-InsecureBankv2.git', severity: 'high' },
  // More CVE
  { label: '🚨 CVE-2021-44228 (Log4Shell) PoC',            url: 'https://github.com/christophetd/log4shell-vulnerable-app.git', severity: 'critical' },
  { label: '🚨 CVE-2022-0811 (CRI-O escape) demo',         url: 'https://github.com/MaherAzzouzi/CVE-2022-0811.git',  severity: 'critical' },
  // Misc
  { label: '🔥 SSRF test server',                           url: 'https://github.com/assetnote/surf.git',              severity: 'medium' },
  { label: '🕳️ XXE injection demo',                          url: 'https://github.com/c0ny1/xxe-lab.git',              severity: 'high' },
  { label: '💡 SQLMap — SQL injection tool',                url: 'https://github.com/sqlmapproject/sqlmap.git',        severity: 'high' },
]

const selectedDemo = ref('')
const customUrl = ref('')
const search = ref('')
const open = ref(false)

const filtered = computed(() => {
  const q = search.value.toLowerCase()
  return DEMO_REPOS.filter(r =>
    !q || r.label.toLowerCase().includes(q) || r.severity.includes(q)
  )
})

const effectiveUrl = computed(() => selectedDemo.value || customUrl.value.trim())

function pick(repo) {
  selectedDemo.value = repo.url
  search.value = ''
  open.value = false
}
function clear() {
  selectedDemo.value = ''
  search.value = ''
}
function startScan() {
  if (effectiveUrl.value) emit('start-scan', effectiveUrl.value)
}

function handleClick(e) {
  if (!e.target.closest('.picker-wrap')) open.value = false
}
onMounted(() => document.addEventListener('click', handleClick))
onBeforeUnmount(() => document.removeEventListener('click', handleClick))
</script>

<style scoped>
.scan-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  max-width: 900px;
}

.label {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.demo-select {
  width: 100%;
  background: rgba(8,12,24,0.8);
  border: 1px solid var(--cyan-border);
  border-radius: 10px;
  color: var(--text);
  padding: 0.65rem 1rem;
  font-size: 0.88rem;
  transition: border-color 0.2s;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath fill='%238b949e' d='M1 1l5 5 5-5'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 1rem center;
}
.demo-select:focus { border-color: var(--cyan); }
.demo-select option { background: #0d1117; }

.url-row {
  display: flex;
  gap: 0.75rem;
}

.url-input {
  flex: 1;
  background: rgba(8,12,24,0.8);
  border: 1px solid var(--cyan-border);
  border-radius: 10px;
  color: var(--text);
  padding: 0.65rem 1rem;
  font-size: 0.88rem;
  font-family: var(--mono);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.url-input:focus {
  border-color: var(--cyan);
  box-shadow: 0 0 0 3px rgba(0,180,255,0.12);
}
.url-input::placeholder { color: #334155; }
.url-input:disabled { opacity: 0.4; cursor: not-allowed; }

.scan-btn {
  background: linear-gradient(135deg, #0084cc, #0060aa);
  border: 1px solid rgba(0,180,255,0.3);
  border-radius: 10px;
  color: #fff;
  font-size: 0.88rem;
  font-weight: 600;
  padding: 0.65rem 1.75rem;
  box-shadow: 0 0 20px rgba(0,132,204,0.25);
  transition: all 0.2s;
  white-space: nowrap;
}
.scan-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #00a0e8, #0084cc);
  box-shadow: 0 0 30px rgba(0,180,255,0.35);
  transform: translateY(-1px);
}
.scan-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

/* ── Searchable picker ── */
.picker-wrap { position: relative; margin-bottom: 0.75rem; }
.picker-search {
  width: 100%; background: rgba(0,0,0,0.4);
  border: 1px solid rgba(0,180,255,0.2); border-radius: 10px;
  color: #e2e8f0; font-size: 0.88rem; padding: 0.65rem 1rem;
  font-family: inherit; outline: none; transition: border-color 0.2s;
}
.picker-search:focus { border-color: rgba(0,180,255,0.5); }
.picker-drop {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0;
  background: rgba(8,12,24,0.98); border: 1px solid rgba(0,180,255,0.2);
  border-radius: 10px; max-height: 260px; overflow-y: auto;
  z-index: 999; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
}
.picker-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.5rem 1rem; cursor: pointer; gap: 0.5rem;
  transition: background 0.15s;
}
.picker-item:hover, .picker-item.selected { background: rgba(0,180,255,0.08); }
.picker-label { font-size: 0.82rem; color: #cbd5e1; flex: 1; }
.picker-tag {
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; padding: 2px 6px; border-radius: 4px;
  flex-shrink: 0;
}
.picker-tag.critical { background: rgba(239,68,68,0.15); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
.picker-tag.high     { background: rgba(249,115,22,0.12); color: #f97316; border: 1px solid rgba(249,115,22,0.3); }
.picker-tag.medium   { background: rgba(234,179,8,0.1);  color: #eab308; border: 1px solid rgba(234,179,8,0.3); }
.picker-tag.low      { background: rgba(59,130,246,0.1); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3); }
.picker-chosen {
  display: flex; align-items: center; justify-content: space-between;
  background: rgba(0,180,255,0.06); border: 1px solid rgba(0,180,255,0.2);
  border-radius: 8px; padding: 0.5rem 0.85rem; margin-top: 0.4rem;
  font-size: 0.82rem; color: #00b4ff;
}
.picker-clear {
  background: none; border: none; color: #475569;
  cursor: pointer; font-size: 0.9rem; padding: 0 0.2rem;
}
.picker-clear:hover { color: #e2e8f0; }
</style>
