<template>
  <!-- Overlay backdrop when open -->
  <div v-if="open" class="backdrop" @click="$emit('close')"></div>

  <div class="drawer" :class="{ open }">
    <div class="drawer-header">
      <span>🤖</span>
      <span>Agent Chat — Kata VM Sandbox</span>
      <button class="close-btn" @click="$emit('close')">✕</button>
    </div>

    <div class="input-row">
      <input
        v-model="inputText"
        type="text"
        placeholder="Ask the security agent anything…"
        @keydown.enter="send"
        ref="inputEl"
      />
      <button class="send-btn" @click="send" :disabled="sending">Send</button>
    </div>

    <div class="messages" ref="messagesEl">
      <!-- Typing indicator while waiting for nemotron -->
      <div v-if="sending" class="msg assistant typing-row">
        <div class="avatar">🤖</div>
        <div class="bubble typing">
          <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          <span class="waiting-text">Waiting on nemotron…</span>
        </div>
      </div>
      <div v-if="messages.length === 0 && !sending" class="empty">
        No messages yet. Ask the agent anything about the scan or codebase.
      </div>
      <div v-else>
        <div
          v-for="(msg, i) in [...messages].reverse()"
          :key="i"
          class="msg"
          :class="msg.role"
        >
          <div class="avatar">{{ msg.role === 'user' ? '🧑' : '🤖' }}</div>
          <div class="bubble">{{ msg.text }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { sendChat } from '../api.js'

const props = defineProps({ open: Boolean, scanId: String })
defineEmits(['close'])

const inputText = ref('')
const messages = ref([])
const sending = ref(false)
const inputEl = ref(null)
const messagesEl = ref(null)

watch(() => props.open, (v) => {
  if (v) nextTick(() => inputEl.value?.focus())
})

async function send() {
  const msg = inputText.value.trim()
  if (!msg || sending.value) return
  inputText.value = ''
  messages.value.push({ role: 'user', text: msg })
  sending.value = true
  try {
    const res = await sendChat(msg, props.scanId)
    messages.value.push({ role: 'assistant', text: res.text })
  } catch {
    messages.value.push({ role: 'assistant', text: 'Error: could not reach agent.' })
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  z-index: 8998;
}

.drawer {
  position: fixed;
  top: 0; right: 0;
  width: 380px;
  height: 100vh;
  background: rgba(5,8,16,0.98);
  border-left: 1px solid rgba(0,180,255,0.22);
  box-shadow: -8px 0 40px rgba(0,0,0,0.6);
  display: flex;
  flex-direction: column;
  z-index: 8999;
  transform: translateX(100%);
  transition: transform 0.28s cubic-bezier(0.4,0,0.2,1);
  backdrop-filter: blur(20px);
}
.drawer.open { transform: translateX(0); }

.drawer-header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  background: linear-gradient(90deg, rgba(0,180,255,0.09), rgba(0,180,255,0.03));
  border-bottom: 1px solid rgba(0,180,255,0.15);
  padding: 0.85rem 1rem;
  font-size: 0.73rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #475569;
  flex-shrink: 0;
}
.close-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: #475569;
  font-size: 1rem;
  cursor: pointer;
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  transition: color 0.2s;
}
.close-btn:hover { color: #e6edf3; }

.input-row {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  flex-shrink: 0;
}

.input-row input {
  flex: 1;
  background: rgba(0,0,0,0.4);
  border: 1px solid rgba(0,180,255,0.2);
  border-radius: 8px;
  color: #e2e8f0;
  font-size: 0.84rem;
  padding: 0.5rem 0.75rem;
  transition: border-color 0.2s;
}
.input-row input:focus { border-color: rgba(0,180,255,0.5); }
.input-row input::placeholder { color: #334155; }

.send-btn {
  background: linear-gradient(135deg,#0060aa,#0084cc);
  border: 1px solid rgba(0,180,255,0.3);
  border-radius: 8px;
  color: #fff;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.5rem 0.9rem;
  transition: opacity 0.2s;
}
.send-btn:hover:not(:disabled) { opacity: 0.85; }
.send-btn:disabled { opacity: 0.4; cursor: default; }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.empty {
  color: #334155;
  font-size: 0.8rem;
  text-align: center;
  padding: 2rem 1rem;
  line-height: 1.6;
}

.msg {
  display: flex;
  gap: 0.6rem;
  align-items: flex-start;
}
.msg.user { flex-direction: row-reverse; }

.avatar {
  width: 28px; height: 28px;
  border-radius: 50%;
  background: rgba(0,180,255,0.1);
  border: 1px solid rgba(0,180,255,0.2);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem;
  flex-shrink: 0;
}

.bubble {
  max-width: 80%;
  background: rgba(15,25,45,0.8);
  border: 1px solid rgba(0,180,255,0.1);
  border-radius: 12px;
  padding: 0.55rem 0.85rem;
  font-size: 0.82rem;
  line-height: 1.5;
  color: #cbd5e1;
  white-space: pre-wrap;
}
.msg.user .bubble {
  background: rgba(0,96,170,0.2);
  border-color: rgba(0,180,255,0.2);
}

.bubble.typing {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
}
.dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: #00b4ff;
  animation: bounce 1.2s infinite;
  flex-shrink: 0;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce {
  0%,60%,100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-5px); opacity: 1; }
}
.waiting-text {
  font-size: 0.75rem;
  color: #475569;
  font-style: italic;
  letter-spacing: 0.02em;
}
</style>
