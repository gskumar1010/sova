<template>
  <div class="scan-wrap">
    <label class="label">Select a demo repo or paste your own URL</label>

    <select v-model="selectedDemo" class="demo-select">
      <option value="">— Select a demo repository —</option>
      <option v-for="repo in DEMO_REPOS" :key="repo.url" :value="repo.url">
        {{ repo.label }}
      </option>
    </select>

    <div class="url-row">
      <input
        v-model="customUrl"
        type="text"
        placeholder="https://github.com/org/repo.git  (or select a demo above)"
        class="url-input"
        :disabled="!!selectedDemo"
        @keydown.enter="startScan"
      />
      <button class="scan-btn" @click="startScan" :disabled="!effectiveUrl">
        Scan →
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const emit = defineEmits(['start-scan'])

const DEMO_REPOS = [
  { label: '🐍 PyGoat — Vulnerable Django app',      url: 'https://github.com/adeyosemanputra/pygoat.git' },
  { label: '🌍 DVWA — Damn Vulnerable Web App',       url: 'https://github.com/digininja/DVWA.git' },
  { label: '☁️ TerraGoat — Terraform misconfigs',      url: 'https://github.com/bridgecrewio/terragoat.git' },
  { label: '🍶 Flask — Python web framework',          url: 'https://github.com/pallets/flask.git' },
  { label: '🧃 Juice Shop — OWASP Node.js app',        url: 'https://github.com/juice-shop/juice-shop.git' },
  { label: '🔑 WebGoat Legacy — Java vulns',           url: 'https://github.com/WebGoat/WebGoat-Legacy.git' },
]

const selectedDemo = ref('')
const customUrl = ref('')

const effectiveUrl = computed(() => selectedDemo.value || customUrl.value.trim())

function startScan() {
  if (effectiveUrl.value) emit('start-scan', effectiveUrl.value)
}
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
</style>
