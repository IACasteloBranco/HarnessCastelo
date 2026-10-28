(() => {
  const installed = Symbol.for('governanca.ai.claude.network.v1');
  if (window[installed] || typeof window.fetch !== 'function') return;
  window[installed] = true;

  const marker = 'governanca-ai-claude-network-v1';
  const originalFetch = window.fetch;
  const maxFrameBytes = 512_000;
  const maxStreamBytes = 2_000_000;
  const readers = new Set();
  let enabled = false;

  window.addEventListener('message', event => {
    if (event.source === window && event.origin === location.origin &&
        event.data?.marker === marker && event.data.phase === 'capture_config') {
      enabled = event.data.enabled === true;
      if (!enabled) for (const reader of readers) reader.cancel().catch(() => {});
    }
  });

  function varint(bytes, cursor) {
    let value = 0;
    let shift = 0;
    for (let index = 0; index < 10 && cursor.offset < bytes.length; index++) {
      const byte = bytes[cursor.offset++];
      value += (byte & 0x7f) * 2 ** shift;
      if (!(byte & 0x80)) return Number.isSafeInteger(value) ? value : null;
      shift += 7;
    }
    return null;
  }

  function fields(bytes) {
    const result = [];
    const cursor = {offset: 0};
    while (cursor.offset < bytes.length) {
      const key = varint(bytes, cursor);
      if (!key || key === null) return null;
      const number = Math.floor(key / 8);
      const wire = key & 7;
      if (!number) return null;
      let value;
      if (wire === 0) value = varint(bytes, cursor);
      else if (wire === 1 && cursor.offset + 8 <= bytes.length) {
        value = bytes.subarray(cursor.offset, cursor.offset + 8);
        cursor.offset += 8;
      } else if (wire === 2) {
        const length = varint(bytes, cursor);
        if (length === null || length > maxFrameBytes || cursor.offset + length > bytes.length) return null;
        value = bytes.subarray(cursor.offset, cursor.offset + length);
        cursor.offset += length;
      } else if (wire === 5 && cursor.offset + 4 <= bytes.length) {
        value = bytes.subarray(cursor.offset, cursor.offset + 4);
        cursor.offset += 4;
      } else return null;
      if (value === null) return null;
      result.push({number, wire, value});
      if (result.length > 4096) return null;
    }
    return result;
  }

  function assistantText(payload) {
    // shortcut: recognizes only the observed role/text field paths; replace with Claude's generated schema if those paths change.
    const found = new Map();
    function walk(bytes, path, depth) {
      if (depth > 6) return;
      const entries = fields(bytes);
      if (!entries) return;
      for (const entry of entries) {
        const next = [...path, entry.number];
        const key = next.join('.');
        if (key === '1.1.3.3' && entry.wire === 0) found.set('role', entry.value);
        if (key === '1.1.5.9' && entry.wire === 2) {
          try { found.set('text', new TextDecoder('utf-8', {fatal: true}).decode(entry.value)); }
          catch { found.delete('text'); }
        }
        if (entry.wire === 2 && depth < 6) walk(entry.value, next, depth + 1);
      }
    }
    walk(payload, [], 0);
    const text = found.get('text');
    return found.get('role') === 2 && typeof text === 'string' && text.length > 0 && text.length <= 100_000
      ? text : null;
  }

  function attemptId() {
    const root = document.documentElement;
    const id = root?.getAttribute('data-governanca-probe-attempt');
    const until = Number(root?.getAttribute('data-governanca-probe-until'));
    return /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id || '') && Date.now() <= until
      ? id : null;
  }

  function emit(text, id) {
    if (!enabled || !id) return;
    window.postMessage({marker, phase: 'assistant_text', attemptId: id, text}, location.origin);
  }

  async function inspect(response, id) {
    if (!enabled || !id || response?.status !== 200 || !response?.body ||
        !/^application\/connect\+proto(?:\s*;|$)/i.test(response.headers?.get?.('content-type') || '')) return;
    let reader;
    try { reader = response.clone().body.getReader(); } catch { return; }
    if (readers.size >= 4) { try { await reader.cancel(); } catch {} return; }
    readers.add(reader);
    const timeout = setTimeout(() => reader.cancel().catch(() => {}), 30_000);
    let pending = new Uint8Array();
    let total = 0;
    let frames = 0;
    try {
      while (total < maxStreamBytes && frames < 256) {
        const {done, value} = await reader.read();
        if (done) return;
        total += value.byteLength;
        if (total > maxStreamBytes) break;
        const joined = new Uint8Array(pending.length + value.length);
        joined.set(pending);
        joined.set(value, pending.length);
        let offset = 0;
        while (joined.length - offset >= 5) {
          const flags = joined[offset];
          const length = new DataView(joined.buffer, joined.byteOffset + offset + 1, 4).getUint32(0);
          if ((flags !== 0 && flags !== 2) || length > maxFrameBytes) return;
          if (joined.length - offset < 5 + length) break;
          const payload = joined.subarray(offset + 5, offset + 5 + length);
          if (flags === 0) {
            const text = assistantText(payload);
            if (text) emit(text, id);
          }
          frames++;
          offset += 5 + length;
          if (flags === 2) { await reader.cancel(); return; }
        }
        pending = joined.slice(offset);
        if (pending.length > maxFrameBytes + 5) break;
      }
    } catch { /* A clone read failure must not affect the page response. */ }
    finally {
      clearTimeout(timeout);
      readers.delete(reader);
      try { await reader.cancel(); } catch {}
    }
  }

  window.fetch = new Proxy(originalFetch, {
    apply(target, thisArg, args) {
      let isTimeline = false;
      const id = attemptId();
      try {
        const input = args[0];
        const url = new URL(typeof input === 'string' ? input : input?.url || String(input), location.href);
        const method = String(args[1]?.method || input?.method || 'GET').toUpperCase();
        isTimeline = enabled && id && url.origin === location.origin && method === 'POST' &&
          /^\/claudeai-rpc\/[^/]+\/StreamTimeline\/?$/.test(url.pathname);
      } catch {}
      const response = Reflect.apply(target, thisArg, args);
      if (isTimeline) Promise.resolve(response).then(result => inspect(result, id)).catch(() => {});
      return response;
    }
  });
})();
