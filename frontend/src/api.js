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
  let buffer = '';
  let finalResult = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // keep incomplete last line

    let eventType = null;
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        const data = line.slice(6);
        try {
          const parsed = JSON.parse(data);
          if (eventType === 'progress' && onProgress) {
            onProgress(parsed);
          } else if (eventType === 'result') {
            finalResult = parsed;
          } else if (eventType === 'error') {
            throw new Error(parsed.error || 'Pipeline error');
          }
        } catch (e) {
          if (eventType === 'error') throw e;
          // Ignore JSON parse errors for incomplete chunks
        }
        eventType = null;
      }
    }
  }

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
