(() => {
  const INSTALLED = Symbol.for('governanca.ai.network.probe.v1');
  if (window[INSTALLED]) return;
  window[INSTALLED] = true;

  const MARKER = 'governanca-ai-network-probe-v1';
  const adapter = globalThis.GovernancaCaptureAdapter;
  let captureEnabled = false;
  const eventCounts = new Map();
  let nextRequestId = 0;

  function captureAttempt(path, method) {
    if (method !== adapter.requestMethod || path !== adapter.requestPath) return null;
    const root = document.documentElement;
    const id = root?.getAttribute('data-governanca-probe-attempt');
    const until = Number(root?.getAttribute('data-governanca-probe-until'));
    root?.removeAttribute('data-governanca-probe-attempt');
    root?.removeAttribute('data-governanca-probe-until');
    return /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id || '') &&
      Date.now() <= until ? id : crypto.randomUUID();
  }

  function artifactTarget(input, method) {
    if (method !== 'GET') return null;
    try {
      const url = new URL(typeof input === 'string' ? input : input?.url || String(input), location.href);
      if (url.origin !== location.origin) return null;
      if (url.pathname === '/backend-api/estuary/content') return 'download_headers';
    } catch {}
    return null;
  }

  function safeTarget(input) {
    try {
      const url = new URL(typeof input === 'string' ? input : input?.url || String(input), location.href);
      const expected = new URL(location.href);
      if (url.protocol === 'wss:') url.protocol = 'https:';
      if (url.protocol === 'ws:') url.protocol = 'http:';
      if (url.origin !== expected.origin) return null;
      const knownSegments = new Set(['backend-api', 'f', 'conversation', 'prepare', 'batch', 'finalize',
        'sentinel', 'models', 'accounts', 'conversations', 'messages', 'feedback', 'files', 'upload']);
      const path = url.pathname.split('/').map(part =>
        knownSegments.has(part) ? part : part ? ':id' : ''
      ).join('/').slice(0, 240);
      return path || '/';
    } catch { return null; }
  }

  function emit(attemptId, transport, phase, details = {}) {
    if (!attemptId) return;
    const count = eventCounts.get(attemptId) || 0;
    if (count >= 80) return;
    eventCounts.set(attemptId, count + 1);
    if (eventCounts.size > 20) eventCounts.delete(eventCounts.keys().next().value);
    try {
      window.postMessage({marker: MARKER, attemptId, transport, phase, at: Date.now(), ...details}, location.origin);
    } catch {}
  }

  const mime = value => String(value || '').split(';', 1)[0].trim().toLowerCase().slice(0, 80);
  const methodOf = value => String(value || 'GET').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 12);
  const elapsed = start => Math.max(0, Math.round(performance.now() - start));

  function safeFileName(value) {
    if (typeof value !== 'string') return null;
    const name = value.replace(/[\u0000-\u001f\u007f]/g, '').trim();
    if (!name || name.length > 255 || /[\\/]/.test(name) || name === '.' || name === '..') return null;
    return name;
  }

  function dispositionFileName(value) {
    const header = String(value || '');
    const extended = header.match(/(?:^|;)\s*filename\*\s*=\s*([^;]+)/i);
    if (extended) {
      let encoded = extended[1].trim().replace(/^"|"$/g, '');
      encoded = encoded.replace(/^UTF-8''/i, '');
      try { return safeFileName(decodeURIComponent(encoded)); } catch { return null; }
    }
    const regular = header.match(/(?:^|;)\s*filename\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)/i);
    if (!regular) return null;
    const raw = regular[1].trim();
    return safeFileName(raw.startsWith('"') && raw.endsWith('"') ? raw.slice(1, -1).replace(/\\(.)/g, '$1') : raw);
  }

  function conversationContext(href) {
    try {
      const url = new URL(href);
      if (url.origin !== location.origin) return null;
      const match = url.pathname.match(/^\/(?:g\/[a-zA-Z0-9-]+\/)?c\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i);
      return match ? {conversation_id: match[1], source: 'active_route_at_request'} : null;
    } catch { return null; }
  }

  function emitArtifactMetadata(source, fileName, mimeType, sizeBytes, context, sizeSource) {
    if (!captureEnabled) return;
    const cleanName = safeFileName(fileName);
    const cleanMime = typeof mimeType === 'string' &&
      /^[a-zA-Z0-9!#$&^_.+-]+\/[a-zA-Z0-9!#$&^_.+-]+$/.test(mimeType) ? mimeType.toLowerCase() : null;
    const cleanSize = Number.isSafeInteger(sizeBytes) && sizeBytes >= 0 ? sizeBytes : null;
    if (!cleanName && !cleanMime && cleanSize === null) return;
    window.postMessage({marker: MARKER, phase: 'artifact_metadata', payload: {
      artifact_id: crypto.randomUUID(), platform: 'chatgpt_web', source,
      file_name: cleanName, mime_type: cleanMime, size_bytes: cleanSize,
      conversation_context: context, size_source: sizeSource,
      observed_at: new Date().toISOString()
    }}, location.origin);
  }

  function captureDownloadHeaders(response, context) {
    const fileName = dispositionFileName(response.headers?.get?.('content-disposition'));
    const mimeType = mime(response.headers?.get?.('content-type')) || null;
    const rawLength = response.headers?.get?.('content-length');
    const contentRange = response.headers?.get?.('content-range');
    const contentEncoding = response.headers?.get?.('content-encoding');
    const parsedLength = rawLength && /^\d+$/.test(rawLength) ? Number(rawLength) : null;
    const sizeBytes = response.status === 200 && !contentRange &&
      (!contentEncoding || contentEncoding.toLowerCase() === 'identity') &&
      Number.isSafeInteger(parsedLength) ? parsedLength : null;
    emitArtifactMetadata('download_headers', fileName, mimeType, sizeBytes, context,
      sizeBytes === null ? 'unavailable' : 'content_length');
  }

  async function inspectConversation(response, attemptId, requestId, path) {
    if (!response?.body || typeof TextDecoder !== 'function') return;
    let reader;
    try { reader = response.clone().body.getReader(); }
    catch { return; }
    const decoder = new TextDecoder();
    const types = new Map();
    const shapes = new Map();
    const keyShapes = new Map();
    const patchShapes = new Map();
    const deltaShapes = new Map();
    const lastEvents = [];
    const eventSequence = [];
    let bytes = 0;
    let chunks = 0;
    let frames = 0;
    let doneMarkers = 0;
    let truncated = false;
    let pending = '';
    const textParts = new Map();
    let assistantSeen = false;
    let assistantMessages = 0;
    let textPartSnapshots = 0;
    let textChars = 0;
    let deltaChars = 0;
    let patchChars = 0;
    let captureEmitted = false;
    let assistantFinished = false;
    let assistantEndTurn = false;
    let assistantMessageId = null;
    let currentRole = null;
    const streamStarted = performance.now();
    const knownLabels = new Set(['message', 'delta', 'ping', 'done', 'error', 'completion', 'text', 'output_text', 'token',
      'response', 'response.created', 'response.completed', 'response.output_text.delta',
      'assistant', 'tool', 'finished_successfully', 'in_progress', 'streaming',
      'complete', 'completed', 'stop', 'length', 'interrupted', 'aborted', 'failed']);
    const label = value => typeof value === 'string' ? (knownLabels.has(value) ? value : 'other') : null;
    const summary = () => ({requestId, path, status: response.status,
      contentType: mime(response.headers?.get?.('content-type')), bytes, chunks, frames, doneMarkers,
      protocolDone: doneMarkers > 0, truncated,
      streamElapsedMs: elapsed(streamStarted),
      assistantFinished, assistantEndTurn, assistantActive: currentRole === 'assistant',
      eventTypes: [...types].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => `${name}=${count}`),
      eventShapes: [...shapes].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => `${name}=${count}`),
      eventKeys: [...keyShapes].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => `${name}=${count}`),
      patchShapes: [...patchShapes].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => `${name}=${count}`),
      deltaShapes: [...deltaShapes].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => `${name}=${count}`),
      assistantMessages, textPartSnapshots, textChars, deltaChars, patchChars,
      lastEvents, eventSequence});
    const nextTextPartIndex = () => {
      let next = 0;
      for (const index of textParts.keys()) next = Math.max(next, index + 1);
      return next;
    };
    const joinedText = () => [...textParts].sort((a, b) => a[0] - b[0]).map(([, value]) => value).join('');
    function observeAssistant(message) {
      if (message?.author?.role !== 'assistant') return;
      if ((message.recipient && message.recipient !== 'all') ||
          (message.content?.content_type && message.content.content_type !== 'text')) {
        currentRole = null;
        return;
      }
      if (message.id && assistantMessageId && message.id !== assistantMessageId) {
        textParts.clear();
        assistantFinished = false;
        assistantEndTurn = false;
      }
      if (message.id) assistantMessageId = message.id;
      currentRole = 'assistant';
      assistantSeen = true;
      assistantMessages++;
      if (message.status === 'in_progress' && message.end_turn !== true) assistantFinished = false;
      if (message.end_turn === true) assistantEndTurn = true;
      if (message.status === 'finished_successfully' || message.end_turn === true ||
          ['stop', 'length'].includes(message.metadata?.finish_details?.type)) assistantFinished = true;
      const parts = message.content?.parts;
      if (Array.isArray(parts) && parts.every(part => typeof part === 'string')) {
        textPartSnapshots++;
        textParts.clear();
        parts.forEach((part, index) => textParts.set(index, part));
        textChars = joinedText().length;
      }
    }
    function shapeOf(parsed) {
      if (!parsed || typeof parsed !== 'object') return 'primitive';
      if (Array.isArray(parsed)) return 'array';
      const keys = ['type', 'message', 'delta', 'v', 'p', 'o', 'content', 'status', 'error', 'is_completion']
        .filter(key => Object.hasOwn(parsed, key));
      const content = parsed.message?.content || parsed.content;
      const parts = content?.parts;
      const patchPath = typeof parsed.p === 'string' ?
        /(?:^|\/)content\/parts(?:\/|$)/.test(parsed.p) ? 'parts' :
        /(?:^|\/)status(?:\/|$)/.test(parsed.p) ? 'status' :
        /(?:^|\/)metadata(?:\/|$)/.test(parsed.p) ? 'metadata' :
        /(?:^|\/)content(?:\/|$)/.test(parsed.p) ? 'content' : 'other' : null;
      const valueType = Object.hasOwn(parsed, 'v') ?
        Array.isArray(parsed.v) ? 'array' : parsed.v === null ? 'null' : typeof parsed.v : null;
      const valueKeys = parsed.v && typeof parsed.v === 'object' && !Array.isArray(parsed.v) ?
        ['message', 'content', 'parts', 'status', 'metadata', 'type', 'delta', 'author']
          .filter(key => Object.hasOwn(parsed.v, key)) : [];
      const partType = Array.isArray(parts) ?
        parts.length ? typeof parts[0] : 'empty' : null;
      const operation = typeof parsed.o === 'string' ?
        ['add', 'append', 'replace', 'remove', 'patch'].includes(parsed.o) ? parsed.o : 'other' : null;
      return [`keys-${keys.join('_') || 'other'}`, patchPath && `path-${patchPath}`,
        operation && `op-${operation}`, valueType && `value-${valueType}`,
        valueKeys.length && `vkeys-${valueKeys.join('_')}`, partType && `part-${partType}`]
        .filter(Boolean).join(':').slice(0, 180);
    }
    function processNestedPatches(root) {
      const budget = {nodes: 0};
      const visit = (node, depth) => {
        if (depth > 8 || budget.nodes++ >= 100 || !node || typeof node !== 'object') return;
        if (Array.isArray(node)) { for (const child of node.slice(0, 24)) visit(child, depth + 1); return; }
        if (typeof node.p === 'string') {
          const knownPathParts = new Set(['message', 'content', 'parts', 'text', 'value']);
          const path = node.p.split(/[/.]+/).filter(Boolean).slice(0, 10)
            .map(part => /^\d+$/.test(part) ? 'index' : knownPathParts.has(part) ? part : 'other').join('_');
          const value = node.v;
          const valueType = typeof value === 'string' ? `string_${Math.min(value.length, 100000)}` :
            Array.isArray(value) ? `array_${value.length}` : value === null ? 'null' : typeof value;
          const op = ['add', 'append', 'replace', 'remove', 'patch'].includes(node.o) ? node.o : 'other';
          const shape = `child_path_${path || 'empty'}_op_${op}_value_${valueType}`;
          patchShapes.set(shape, (patchShapes.get(shape) || 0) + 1);
          if (currentRole === 'assistant') {
            const indexed = node.p.match(/(?:^|\/)content\/parts\/(\d+)(?:\/(?:text|value))?$/);
            const patchText = typeof value === 'string' ? value :
              Array.isArray(value) && value.every(part => typeof part === 'string') ?
                value.join('') : null;
            if (indexed && patchText !== null) {
              const index = Number(indexed[1]);
              if (node.o === 'append') textParts.set(index, (textParts.get(index) || '') + patchText);
              else if (node.o === 'replace' || node.o === 'add' || !node.o) textParts.set(index, patchText);
              else truncated = true;
              patchChars += patchText.length;
            } else if (/(?:^|\/)content\/parts$/.test(node.p) &&
                Array.isArray(value) && value.every(part => typeof part === 'string')) {
              if (node.o === 'append') {
                const base = nextTextPartIndex();
                value.forEach((part, index) => textParts.set(base + index, part));
              } else if (node.o === 'replace' || node.o === 'add' || !node.o) {
                textParts.clear(); value.forEach((part, index) => textParts.set(index, part));
              } else truncated = true;
              patchChars += value.reduce((total, part) => total + part.length, 0);
            } else if (/(?:^|\/)content\/parts(?:\/|$)/.test(node.p)) truncated = true;
            if (/(?:^|\/)message\/status$/.test(node.p) && value === 'finished_successfully') assistantFinished = true;
            if (/(?:^|\/)message\/end_turn$/.test(node.p) && value === true) assistantEndTurn = true;
            if (/(?:^|\/)message$/.test(node.p)) observeAssistant(value);
            textChars = joinedText().length;
          }
        }
        if (node.c && typeof node.c === 'object') visit(node.c, depth + 1);
      };
      visit(root, 0);
    }
    function observe(frame) {
      if (!frame.trim()) return;
      frames++;
      const lines = frame.split(/\r?\n/);
      const eventName = label(lines.find(line => line.startsWith('event:'))?.slice(6).trim()) || 'message';
      const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
      if (data === adapter.doneMarker) doneMarkers++;
      let payloadType = null;
      let status = null;
      let finish = null;
      let shape = 'unparsed';
      if (data && data !== adapter.doneMarker && data.length <= 65536) {
        try {
          const parsed = JSON.parse(data);
          payloadType = label(parsed?.type);
          status = label(parsed?.status || parsed?.message?.status);
          finish = label(parsed?.message?.metadata?.finish_details?.type);
          shape = shapeOf(parsed);
          shapes.set(shape, (shapes.get(shape) || 0) + 1);
          const keys = value => value && typeof value === 'object' && !Array.isArray(value)
            ? Object.keys(value).filter(key => /^[a-zA-Z][a-zA-Z0-9_]{0,39}$/.test(key)).slice(0, 12).join('_')
            : '';
          const structure = (value, depth = 0) => {
            if (typeof value === 'string') return `string${Math.min(value.length, 100000)}`;
            if (value === null) return 'null';
            if (Array.isArray(value)) return `array${value.length}_${depth < 2 ? structure(value[0], depth + 1) : 'nested'}`;
            if (value && typeof value === 'object') {
              const children = depth < 2 ? Object.keys(value).filter(key => /^[a-zA-Z][a-zA-Z0-9_]{0,39}$/.test(key))
                .slice(0, 5).map(key => `${key}_${structure(value[key], depth + 1)}`).join('_') : '';
              return `object_${keys(value) || 'empty'}${children ? `_${children}` : ''}`;
            }
            return typeof value;
          };
          const part0 = parsed?.message?.content?.parts?.[0] || parsed?.v?.message?.content?.parts?.[0];
          const keyShape = [
            ['root', parsed], ['message', parsed?.message], ['content', parsed?.message?.content],
            ['v', parsed?.v], ['vmessage', parsed?.v?.message], ['vcontent', parsed?.v?.message?.content],
            ['delta', parsed?.delta], ['deltamessage', parsed?.delta?.message], ['part0', part0]
          ].map(([name, value]) => {
            const objectKeys = keys(value);
            if (objectKeys) return `${name}-${objectKeys}`;
            if (name === 'part0' && value !== undefined) return `part0-${Array.isArray(value) ? 'array' : typeof value}`;
            return '';
          }).filter(Boolean).join(':').slice(0, 220);
          if (keyShape) keyShapes.set(keyShape, (keyShapes.get(keyShape) || 0) + 1);
          if (typeof parsed?.p === 'string') {
            const knownPathParts = new Set(['message', 'content', 'parts', 'text', 'author', 'role',
              'metadata', 'status', 'finish_details', 'recipient', 'channel', 'type', 'content_type']);
            const path = parsed.p.split(/[/.]+/).filter(Boolean).slice(0, 10)
              .map(part => /^\d+$/.test(part) ? 'index' : knownPathParts.has(part) ? part : 'other').join('_');
            const value = parsed.v;
            const valueShape = Array.isArray(value) ? `array${value.length}` : value === null ? 'null' : typeof value;
            const valueLength = typeof value === 'string' ? `_${Math.min(value.length, 100000)}` : '';
            const patchShape = `path_${path || 'empty'}_op_${['add', 'append', 'replace', 'remove', 'patch'].includes(parsed.o) ? parsed.o : 'other'}_value_${valueShape}${valueLength}`;
            patchShapes.set(patchShape, (patchShapes.get(patchShape) || 0) + 1);
          }
          const isDelta = eventName === 'delta' || parsed?.type === 'delta';
          if (isDelta) {
            const token = parsed?.token;
            const tokenShape = typeof parsed === 'string' ? `payload_string_${Math.min(parsed.length, 100000)}` :
              typeof token === 'string' ? `string_${Math.min(token.length, 100000)}` :
              Array.isArray(token) ? `array_${token.length}_${typeof token[0]}` :
              token && typeof token === 'object' ? `object_${keys(token) || 'empty'}` : typeof token;
            const deltaShape = `event_${eventName}_type_${label(parsed?.type) || 'none'}_kind_${label(parsed?.kind) || 'none'}_root_${keys(parsed) || typeof parsed}_c_${structure(parsed?.c)}_v_${structure(parsed?.v)}_token_${tokenShape}`.slice(0, 200);
            deltaShapes.set(deltaShape, (deltaShapes.get(deltaShape) || 0) + 1);
          }
          // DPU snapshots may wrap the message under `v.message`; direct
          // `message` is used by the older SSE payload shape.
          const message = parsed?.message || parsed?.v?.message;
          const author = message?.author?.role;
          const token = parsed?.token;
          const deltaValues = [typeof parsed === 'string' ? parsed : null, token, parsed?.delta,
            parsed?.text, parsed?.content, parsed?.value, parsed?.message?.content?.text,
            parsed?.delta?.text, parsed?.delta?.content,
            token && typeof token === 'object' ? token.text : null,
            token && typeof token === 'object' ? token.value : null,
            token && typeof token === 'object' ? token.content : null];
          const deltaTextLength = deltaValues.find(value => typeof value === 'string')?.length ??
            (Array.isArray(token) && token.every(part => typeof part === 'string') ?
              token.reduce((total, part) => total + part.length, 0) : null);
          if (isDelta && Number.isSafeInteger(deltaTextLength) && deltaTextLength <= 100_000 &&
              deltaChars + deltaTextLength <= 100_000) {
            deltaChars += deltaTextLength;
          }
          if (author === 'assistant') {
            observeAssistant(message);
          } else if (author && author !== 'assistant') {
            currentRole = author;
          } else if (currentRole === 'assistant' && typeof parsed?.p === 'string') {
            const match = parsed.p.match(/(?:^|\/)content\/parts\/(\d+)(?:\/(?:text|value))?$/);
            const value = typeof parsed.v === 'string' ? parsed.v
              : Array.isArray(parsed.v) && parsed.v.every(part => typeof part === 'string') ? parsed.v.join('') : null;
            if (match && value !== null) {
              const index = Number(match[1]);
              if (parsed.o === 'append') textParts.set(index, (textParts.get(index) || '') + value);
              else if (parsed.o === 'replace' || parsed.o === 'add' || !parsed.o) textParts.set(index, value);
              else truncated = true;
              textChars = joinedText().length;
            } else if (/(?:^|\/)content\/parts$/.test(parsed.p) &&
                Array.isArray(parsed.v) && parsed.v.every(part => typeof part === 'string')) {
              if (parsed.o === 'append') {
                const base = nextTextPartIndex();
                parsed.v.forEach((part, index) => textParts.set(base + index, part));
              }
              else if (['replace', 'add', undefined].includes(parsed.o)) {
                textParts.clear(); parsed.v.forEach((part, index) => textParts.set(index, part));
              } else truncated = true;
              textChars = joinedText().length;
            } else if (/(?:^|\/)content\/parts(?:\/|$)/.test(parsed.p)) truncated = true;
          }
          if (isDelta && currentRole === 'assistant' && typeof parsed?.p !== 'string' &&
              typeof parsed?.v === 'string') {
            const index = nextTextPartIndex() - 1;
            if (textChars + parsed.v.length <= 100000) {
              textParts.set(Math.max(index, 0), (textParts.get(Math.max(index, 0)) || '') + parsed.v);
              textChars = joinedText().length;
            } else truncated = true;
          }
          if (currentRole === 'assistant' && /(?:^|\/)message\/status$/.test(parsed?.p || '') &&
              parsed.v === 'finished_successfully') assistantFinished = true;
          if (currentRole === 'assistant' && /(?:^|\/)message\/end_turn$/.test(parsed?.p || '') &&
              parsed.v === true) assistantEndTurn = true;
          if (/(?:^|\/)message$/.test(parsed?.p || '')) observeAssistant(parsed.v);
          if (parsed?.c && typeof parsed.c === 'object') processNestedPatches(parsed.c);
          if (Array.isArray(parsed?.v)) processNestedPatches(parsed.v);
        } catch {
          if (eventName === 'delta' && data.trim() && data.length <= 100_000 &&
              deltaChars + data.length <= 100_000) {
            deltaChars += data.length;
          }
        }
      }
      const kind = [eventName, payloadType, status, finish].filter(Boolean).join(':').slice(0, 180);
      types.set(kind, (types.get(kind) || 0) + 1);
      lastEvents.push(kind);
      if (lastEvents.length > 8) lastEvents.shift();
      if (eventSequence.length < 32) eventSequence.push(`${kind}--${shape}`.slice(0, 200));
    }
    function emitCapture(readerDone, readerAbortedAfterDone = false) {
      if (!captureEnabled || captureEmitted || !assistantSeen) return;
      const text = joinedText();
      const responseChars = text.length;
      if (!responseChars || responseChars > 100000) return;
      captureEmitted = true;
      // The terminal [DONE] marker is the authoritative end of this SSE
      // response. Completion metadata is useful, but some DPU snapshots
      // encode it as patches that do not contain a full message object.
      const protocolDone = doneMarkers > 0;
      const complete = protocolDone && doneMarkers === 1 &&
        (readerDone || readerAbortedAfterDone) && !truncated;
      emit(attemptId, 'fetch', 'stream_capture', {...summary(), responseChars,
        captureStatus: complete ? 'complete' : 'incomplete', readerDone, readerAbortedAfterDone,
        protocolDone, truncated, text});
    }
    try {
      while (true) {
        if (!captureEnabled) {
          await reader.cancel();
          return;
        }
        const {done, value} = await reader.read();
        if (done) break;
        chunks++;
        bytes += value?.byteLength || 0;
        if (bytes > 4_000_000) { truncated = true; continue; }
        pending = (pending + decoder.decode(value, {stream: true})).replace(/\r\n/g, '\n');
        let boundary;
        while ((boundary = pending.indexOf('\n\n')) >= 0) {
          observe(pending.slice(0, boundary));
          pending = pending.slice(boundary + 2);
        }
        if (pending.length > 131072) { pending = ''; truncated = true; }
      }
      if (!truncated) {
        pending += decoder.decode();
        if (pending.trim()) observe(pending);
      }
      emitCapture(true);
      emit(attemptId, 'fetch', 'stream_summary', {...summary(), readerDone: true});
    } catch (error) {
      const hasTrailingFrame = Boolean(pending.trim());
      if (hasTrailingFrame) observe(pending);
      const readerAbortedAfterDone = error?.name === 'AbortError' && doneMarkers > 0 && !truncated && !hasTrailingFrame;
      emitCapture(false, readerAbortedAfterDone);
      const allowedErrors = new Set(['AbortError', 'TypeError', 'NetworkError', 'TimeoutError', 'InvalidStateError']);
      emit(attemptId, 'fetch', 'stream_error', {...summary(), readerDone: false,
        readerAbortedAfterDone,
        errorKind: allowedErrors.has(error?.name) ? error.name : 'other'});
    }
  }

  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data;
    if (data?.marker === MARKER && data.phase === 'capture_config')
      captureEnabled = data.enabled === true;
  });

  if (typeof window.fetch === 'function') {
    const nativeFetch = window.fetch;
    window.fetch = new Proxy(nativeFetch, {
      apply(target, thisArg, args) {
        const path = safeTarget(args[0]);
        const method = methodOf(args[1]?.method || args[0]?.method);
        const artifactKind = captureEnabled ? artifactTarget(args[0], method) : null;
        const artifactContext = artifactKind ? conversationContext(location.href) : null;
        const attemptId = captureEnabled ? captureAttempt(path, method) : null;
        const requestId = ++nextRequestId;
        const start = performance.now();
        const candidate = Boolean(attemptId);
        if (candidate) emit(attemptId, 'fetch', 'start', {requestId, path, method});
        let result;
        try { result = Reflect.apply(target, thisArg, args); }
        catch (error) {
          if (candidate) emit(attemptId, 'fetch', 'error', {requestId, path, method, elapsedMs: elapsed(start)});
          throw error;
        }
        if (path) Promise.resolve(result).then(response => {
          const contentType = mime(response?.headers?.get?.('content-type'));
          if (candidate || contentType === adapter.contentType) {
            emit(attemptId, 'fetch', 'end', {requestId, path, method, status: response?.status,
              contentType, hasBody: Boolean(response?.body), elapsedMs: elapsed(start)});
          }
          if (candidate && response?.ok && response?.body && contentType === adapter.contentType) {
            void inspectConversation(response, attemptId, requestId, path);
          }
          if (artifactKind === 'download_headers' && response?.ok) captureDownloadHeaders(response, artifactContext);
        }, () => {
          if (candidate) emit(attemptId, 'fetch', 'error', {requestId, path, method, elapsedMs: elapsed(start)});
        });
        return result;
      }
    });
  }

  if (typeof XMLHttpRequest !== 'undefined') {
    const nativeOpen = XMLHttpRequest.prototype.open;
    const nativeSend = XMLHttpRequest.prototype.send;
    const requests = new WeakMap();
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
      requests.set(this, {method: methodOf(method), path: safeTarget(url)});
      return Reflect.apply(nativeOpen, this, [method, url, ...rest]);
    };
    XMLHttpRequest.prototype.send = function(...args) {
      const info = requests.get(this);
      const attemptId = captureEnabled ? captureAttempt(info?.path, info?.method) : null;
      if (attemptId && info?.path) {
        const requestId = ++nextRequestId;
        const start = performance.now();
        const candidate = Boolean(attemptId);
        if (candidate) emit(attemptId, 'xhr', 'start', {requestId, path: info.path, method: info.method});
        this.addEventListener('loadend', () => {
          let contentType = '';
          try { contentType = mime(this.getResponseHeader('content-type')); } catch {}
          if (candidate || contentType === adapter.contentType) {
            emit(attemptId, 'xhr', 'end', {requestId, path: info.path, method: info.method,
              status: this.status, contentType, elapsedMs: elapsed(start)});
          }
        }, {once: true});
      }
      return Reflect.apply(nativeSend, this, args);
    };
  }

  if (typeof window.EventSource === 'function') {
    window.EventSource = new Proxy(window.EventSource, {
      construct(target, args, newTarget) {
        const source = Reflect.construct(target, args, newTarget);
        const path = safeTarget(args[0]);
        if (path) {
          const requestId = ++nextRequestId;
          const firstByAttempt = new Set();
          source.addEventListener('open', () => {});
          source.addEventListener('message', () => {
            const attemptId = null;
            if (attemptId && !firstByAttempt.has(attemptId)) {
              firstByAttempt.add(attemptId);
              emit(attemptId, 'eventsource', 'message_seen', {requestId, path});
            }
          });
          source.addEventListener('error', () => {});
        }
        return source;
      }
    });
  }

  if (typeof window.WebSocket === 'function') {
    window.WebSocket = new Proxy(window.WebSocket, {
      construct(target, args, newTarget) {
        const socket = Reflect.construct(target, args, newTarget);
        const path = safeTarget(args[0]);
        if (path) {
          const requestId = ++nextRequestId;
          const firstByAttempt = new Set();
          socket.addEventListener('open', () => {});
          socket.addEventListener('message', () => {
            const attemptId = null;
            if (attemptId && !firstByAttempt.has(attemptId)) {
              firstByAttempt.add(attemptId);
              emit(attemptId, 'websocket', 'first_message_seen', {requestId, path});
            }
          });
          socket.addEventListener('close', () => {});
        }
        return socket;
      }
    });
  }
})();
