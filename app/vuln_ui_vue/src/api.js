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

export const sendChat = (message, scan_id = null) =>
  fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, scan_id })
  }).then(r => r.json())

export const healthz = () =>
  fetch(`${BASE}/healthz`).then(r => r.json())
