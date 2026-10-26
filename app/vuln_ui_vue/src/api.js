const BASE = ''

export const startScan = (git_url) =>
  fetch(`${BASE}/api/scan/full`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ git_url })
  }).then(r => r.json())

export const streamScan = (scan_id) =>
  new EventSource(`${BASE}/api/scan/stream/${scan_id}`)

export const getResult = (scan_id) =>
  fetch(`${BASE}/api/scan/full-result/${scan_id}`).then(r => r.json())

export const sendChat = async (message, scan_id = null) => {
  // Submit job
  const res = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, scan_id })
  })
  const { job_id } = await res.json()
  // Poll until done (no browser timeout risk)
  while (true) {
    await new Promise(r => setTimeout(r, 3000))
    const poll = await fetch(`${BASE}/api/chat/${job_id}`)
    const data = await poll.json()
    if (data.status === 'done') return { role: 'assistant', text: data.text }
  }
}

export const healthz = () =>
  fetch(`${BASE}/healthz`).then(r => r.json())
