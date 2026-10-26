import { ref, watch } from 'vue'

/**
 * Animates a number from 0 to `target` using easeOutExpo.
 * Fully defensive: never throws, falls back to the target value on any error.
 */
export function useCountUp(targetRef, duration = 1200) {
  const display = ref(0)
  let timer = null

  watch(targetRef, (newVal) => {
    const to = Math.round(newVal || 0)
    if (to === 0) { display.value = 0; return }

    // Use setInterval instead of RAF for broader compatibility
    if (timer) clearInterval(timer)
    const start = Date.now()
    display.value = 0

    timer = setInterval(() => {
      try {
        const elapsed = Date.now() - start
        const progress = Math.min(elapsed / duration, 1)
        const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)
        display.value = Math.round(to * eased)
        if (progress >= 1) {
          display.value = to
          clearInterval(timer)
          timer = null
        }
      } catch {
        display.value = to
        clearInterval(timer)
        timer = null
      }
    }, 16) // ~60fps
  }, { immediate: true })

  return display
}
