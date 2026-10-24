<template>
  <header class="banner">
    <div class="banner-left">
      <img src="/sova_logo.png" class="owl" alt="SOVA owl" />
      <div class="brand">
        <div class="title">
          <span class="initial">S</span>overeign
          <span class="initial">O</span>versight &amp;
          <span class="initial">V</span>ulnerability
          <span class="initial">A</span>gent
        </div>
      </div>
    </div>
    <div class="banner-right">
      <span class="pill">
        <span class="dot green"></span>Kata VM
      </span>
      <span class="pill">
        <span class="dot cyan"></span>OpenShell
      </span>
      <span class="pill">
        <span class="dot red"></span>Egress Blocked
      </span>
      <span class="pill dimmed">Red Hat OpenShift AI · DEMOJam 2027</span>
      <button class="chat-pill" :class="{ active: chatOpen }" @click="$emit('toggle-chat')">
        {{ chatOpen ? '✕ Chat' : '💬 Chat' }}
      </button>
    </div>
  </header>
</template>

<script setup>
defineProps({ chatOpen: Boolean })
defineEmits(['toggle-chat'])
</script>

<style scoped>
.banner {
  width: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  background: linear-gradient(90deg, rgba(5,8,16,0.99) 0%, rgba(0,25,50,0.96) 100%);
  border-bottom: 1px solid rgba(0,180,255,0.15);
  padding: 4rem 2rem 0;
  flex-wrap: wrap;
  gap: 0.5rem;
  overflow: visible;
  position: relative;
  z-index: 2; /* sit above main content so owl branch shows */
}

.banner-left {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
}

.owl {
  height: 155px;
  width: auto;
  position: relative;
  bottom: -35px;
  flex-shrink: 0;
  filter: drop-shadow(0 0 10px rgba(0,180,255,0.25));
  z-index: 10;
}

.brand { padding-bottom: 0.65rem; }

.title {
  font-size: 1.3rem;
  font-weight: 500;
  color: #94a3b8;
  letter-spacing: 0.01em;
  word-spacing: 0.35em;
  line-height: 1.3;
}

.initial {
  font-size: 2rem;
  font-weight: 800;
  color: #f1f5f9;
  letter-spacing: 0.02em;
  line-height: 1;
  margin-right: 0.03em;
}

.banner-right {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
  padding-bottom: 0.65rem;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: rgba(0,180,255,0.06);
  border: 1px solid rgba(0,180,255,0.18);
  border-radius: 100px;
  padding: 0.28rem 0.85rem;
  font-size: 0.72rem;
  font-weight: 500;
  color: #94a3b8;
  user-select: none;
}

.pill.dimmed {
  color: #475569;
  border-color: rgba(255,255,255,0.06);
  background: transparent;
  font-size: 0.68rem;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot.green { background: #22c55e; box-shadow: 0 0 6px #22c55e; }
.dot.cyan  { background: #00b4ff; box-shadow: 0 0 6px #00b4ff; }
.dot.red   { background: #ef4444; box-shadow: 0 0 6px #ef4444; }

.chat-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: linear-gradient(135deg, #0060aa, #0084cc);
  border: 1px solid rgba(0,180,255,0.4);
  border-radius: 100px;
  padding: 0.32rem 0.9rem;
  font-size: 0.74rem;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  box-shadow: 0 0 16px rgba(0,132,204,0.35);
  letter-spacing: 0.02em;
  transition: background 0.2s;
  white-space: nowrap;
}
.chat-pill:hover { background: linear-gradient(135deg,#0084cc,#00a0e8); }
.chat-pill.active { background: rgba(239,68,68,0.2); border-color: rgba(239,68,68,0.5); color: #fca5a5; box-shadow: none; }
</style>
