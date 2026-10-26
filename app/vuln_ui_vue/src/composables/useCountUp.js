import { ref, watch } from 'vue'

/**
 * Animates a number from 0 to `target` using easeOutExpo.
 * Returns a reactive `display` value that updates every frame.
 */
export function useCountUp(targetRef, duration = 1200) {
  const display = ref(0)
  let raf = null

  function animate(from, to, start) {
    const elapsed = performance.now() - start
    const progress = Math.min(elapsed / duration, 1)
    // easeOutExpo — fast start, slow finish
    const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)
    display.value = Math.round(from + (to - from) * eased)
    if (progress < 1) {
      raf = requestAnimationFrame(() => animate(from, to, start))
    } else {
      display.value = to
    }
  }

  watch(targetRef, (newVal) => {
    if (raf) cancelAnimationFrame(raf)
    const from = 0          // always count from 0 when new results arrive
    const to = newVal || 0
    if (to === 0) { display.value = 0; return }
    animate(from, to, performance.now())
  }, { immediate: true })

  return display
}
