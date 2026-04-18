// Prod: set VITE_API_BASE in Vercel (e.g. "https://api.bhavyagupta.dev")
// Local dev: leave unset — Vite proxy (vite.config.js) forwards /session and
// /attachment to the FastAPI dev server.
const API_BASE = import.meta.env.VITE_API_BASE || '';

export async function startSession(packageId) {
  const url = packageId && packageId !== 'custom'
    ? `${API_BASE}/session/start?package=${encodeURIComponent(packageId)}`
    : `${API_BASE}/session/start`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) throw new Error(`Start session failed: ${res.status}`);
  return res.json();
}

/**
 * Run evaluation with SSE progress streaming.
 * @param {string} sessionId
 * @param {object} payload - { evaluation_date, lp_admission_date, gp_claimed_fee, email_dataset }
 * @param {function} onProgress - called with { stage, detail } for each progress event
 * @returns {Promise<object>} - the final result
 */
export async function evaluate(sessionId, payload, onProgress) {
  const res = await fetch(`${API_BASE}/session/${sessionId}/evaluate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) throw new Error(`Evaluate failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  // SSE parser state — MUST persist across chunk boundaries. Large events
  // (especially the final `result`) routinely span multiple read() calls, so
  // these cannot be function-local to the while loop.
  let buffer = '';
  let eventType = null;
  let dataBuffer = '';
  let finalResult = null;

  const dispatch = () => {
    // Called on every blank line (per SSE spec, blank line = event terminator).
    if (!eventType || !dataBuffer) {
      eventType = null;
      dataBuffer = '';
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(dataBuffer);
    } catch (e) {
      // Malformed JSON in an event — skip and keep streaming.
      eventType = null;
      dataBuffer = '';
      return;
    }
    if (eventType === 'progress' && onProgress) {
      onProgress(parsed);
    } else if (eventType === 'result') {
      finalResult = parsed;
    } else if (eventType === 'error') {
      eventType = null;
      dataBuffer = '';
      throw new Error(parsed.error || 'Pipeline error');
    }
    eventType = null;
    dataBuffer = '';
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // keep incomplete trailing line for next chunk

    for (const line of lines) {
      if (line === '') {
        dispatch();
      } else if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        // Per SSE spec, multiple data: lines within one event are joined by \n.
        dataBuffer += (dataBuffer ? '\n' : '') + line.slice(6);
      }
    }
  }

  // Flush any residual event (e.g., server didn't send a trailing blank line).
  dispatch();

  if (!finalResult) throw new Error('No result received from pipeline');
  return finalResult;
}

export function attachmentUrl(fileId) {
  return `${API_BASE}/attachment/${fileId}`;
}

export async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const base64 = reader.result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
