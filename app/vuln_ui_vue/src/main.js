import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

const app = createApp(App)

// Surface Vue errors visibly instead of blanking the screen
app.config.errorHandler = (err, instance, info) => {
  console.error('[SOVA error]', err, info)
  const div = document.createElement('div')
  div.style.cssText = 'position:fixed;inset:0;background:#0d1117;color:#ef4444;font-family:monospace;padding:2rem;z-index:9999;overflow:auto;white-space:pre-wrap;'
  div.textContent = `[Vue Error in ${info}]\n\n${err?.stack || err}`
  document.body.appendChild(div)
}

window.addEventListener('unhandledrejection', ev => {
  console.error('[SOVA unhandled]', ev.reason)
})

app.mount('#app')
