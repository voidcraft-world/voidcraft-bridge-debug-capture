/** Send only application-selected state. Redaction runs before data leaves the page. */
export async function send_capture(payload, {
  endpoint = 'http://127.0.0.1:7682/plugin/debug-capture/capture',
  redact = value => value,
  max_bytes = 4096,
  timeout_ms = 5000,
  fetch_impl = globalThis.fetch,
} = {}) {
  const selected = redact(structuredClone(payload));
  if (!selected || Array.isArray(selected) || !Number.isInteger(selected.version)) {
    throw new TypeError('Capture must be an object with an integer version');
  }
  const body = JSON.stringify(selected);
  if (new TextEncoder().encode(body).length > max_bytes) {
    throw new RangeError('Capture exceeds byte budget; select fewer fields');
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout_ms);
  try {
    const response = await fetch_impl(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
      signal: controller.signal, credentials: 'omit',
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Capture failed (${response.status})`);
    return result;
  } finally {
    clearTimeout(timer);
  }
}
