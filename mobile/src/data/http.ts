// GET-JSON helper used for every call to the Pi. Free of React/RN imports so
// it can be tested with plain Node against the real server.
export const REQUEST_TIMEOUT_MS = 4000;

/**
 * Sends `X-API-Key` when a key is set (the Pi's WEBSERVER_API_KEY). Errors are
 * worded for the connection status line: "timed out", "wrong or missing API
 * key" (HTTP 401), "HTTP 500", or the network failure itself.
 */
export async function fetchJson<T>(url: string, apiKey = '', timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal, headers: apiKey ? { 'X-API-Key': apiKey } : undefined });
    if (res.status === 401) throw new Error('wrong or missing API key');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') throw new Error('timed out');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
