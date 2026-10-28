(() => {
  const MARKER = 'governanca-ai-network-probe-v1';
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const platform = location.origin === 'https://claude.ai' ? 'claude_web' : 'chatgpt_web';
  const boundedInt = (value, max = 4_000_000) => Number.isSafeInteger(value) && value >= 0 && value <= max ? value : null;
  const safeLabels = value => Array.isArray(value) ? value.slice(0, 32).filter(item =>
    typeof item === 'string' && /^[a-zA-Z0-9_.:=-]{1,200}$/.test(item)) : [];
  let captureEnabled = false;
  chrome.runtime.onMessage.addListener((message, _sender, reply) => {
    if (message?.type === 'probe_status') reply({active: true, adapterVersion: '0.3.0'});
    if (message?.type === 'probe_config') {
      captureEnabled = message.enabled === true;
      window.postMessage({marker: MARKER, phase: 'capture_config', enabled: captureEnabled}, location.origin);
      reply({applied: true});
    }
  });

  chrome.runtime.sendMessage({type: 'probe_config'}).then(result => {
    if (result?.ok) {
      captureEnabled = result.data?.enabled === true;
      window.postMessage({marker: MARKER, phase: 'capture_config', enabled: captureEnabled}, location.origin);
    }
  }).catch(() => {});

  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin) return;
    const data = event.data;
    if (!data || data.marker !== MARKER) return;
    if (data.phase === 'capture_config') {
      captureEnabled = data.enabled === true;
      return;
    }
    if (data.phase === 'artifact_metadata') {
      const item = data.payload;
      if (!captureEnabled || !item || item.platform !== platform ||
          !UUID.test(item.artifact_id || '') || item.source !== 'download_headers' ||
          typeof item.observed_at !== 'string' ||
          (item.file_name !== null && (typeof item.file_name !== 'string' || !item.file_name ||
            item.file_name.length > 255 || /[\\/\u0000-\u001f\u007f]/.test(item.file_name))) ||
          (item.mime_type !== null && (typeof item.mime_type !== 'string' || item.mime_type.length > 127 ||
            !/^[a-zA-Z0-9!#$&^_.+-]+\/[a-zA-Z0-9!#$&^_.+-]+$/.test(item.mime_type))) ||
          (item.size_bytes !== null && (!Number.isSafeInteger(item.size_bytes) || item.size_bytes < 0 ||
            item.size_bytes > Number.MAX_SAFE_INTEGER)) ||
          (item.conversation_context != null && (!item.conversation_context ||
            !UUID.test(item.conversation_context.conversation_id || '') ||
            item.conversation_context.source !== 'active_route_at_request')) ||
          (item.size_source != null && !['content_length', 'unavailable'].includes(item.size_source)) ||
          (item.file_name === null && item.mime_type === null && item.size_bytes === null)) return;
      chrome.runtime.sendMessage({type: 'artifact_metadata', payload: {
        artifact_id: item.artifact_id, platform, source: item.source,
        file_name: item.file_name, mime_type: item.mime_type, size_bytes: item.size_bytes,
        conversation_context: item.conversation_context || null, size_source: item.size_source || null,
        observed_at: item.observed_at
      }}).catch(() => {});
      return;
    }
    if (!captureEnabled && data.phase === 'stream_capture') return;
    if (data.transport !== 'fetch' || !UUID.test(data.attemptId || '') || data.path !== '/backend-api/f/conversation') return;
    if (['start', 'end', 'stream_summary', 'stream_error'].includes(data.phase)) {
      chrome.runtime.sendMessage({type: 'probe_event', payload: {
        attempt_id: data.attemptId, phase: data.phase, path: data.path,
        method: typeof data.method === 'string' ? data.method : null,
        status: boundedInt(data.status, 599), content_type: data.contentType || '',
        content_kind: data.contentType === 'text/event-stream' ? 'event_stream' :
          data.contentType === 'application/json' ? 'json' : data.contentType ? 'other' : 'none',
        has_body: data.hasBody === true, bytes: boundedInt(data.bytes), chunks: boundedInt(data.chunks),
        frames: boundedInt(data.frames), done_markers: boundedInt(data.doneMarkers, 1000),
        protocol_done: data.protocolDone === true, reader_done: data.readerDone === true,
        reader_aborted_after_done: data.readerAbortedAfterDone === true,
        assistant_finished: data.assistantFinished === true,
        assistant_end_turn: data.assistantEndTurn === true,
        assistant_active: data.assistantActive === true,
        truncated: data.truncated === true, stream_elapsed_ms: boundedInt(data.streamElapsedMs, 180_000),
        assistant_messages: boundedInt(data.assistantMessages, 10_000),
        text_part_snapshots: boundedInt(data.textPartSnapshots, 10_000),
        text_chars: boundedInt(data.textChars, 100_000), delta_chars: boundedInt(data.deltaChars, 100_000),
        patch_chars: boundedInt(data.patchChars, 100_000),
        error_kind: typeof data.errorKind === 'string' ? data.errorKind : null,
        event_types: safeLabels(data.eventTypes), event_shapes: safeLabels(data.eventShapes),
        event_keys: safeLabels(data.eventKeys), patch_shapes: safeLabels(data.patchShapes),
        delta_shapes: safeLabels(data.deltaShapes),
        event_sequence: safeLabels(data.eventSequence),
        at: new Date().toISOString()
      }}).catch(() => {});
      return;
    }
    if (data.phase !== 'stream_capture' ||
        !['complete', 'incomplete'].includes(data.captureStatus) ||
        typeof data.protocolDone !== 'boolean' || typeof data.readerDone !== 'boolean' ||
        typeof data.readerAbortedAfterDone !== 'boolean' || typeof data.truncated !== 'boolean' ||
        (data.captureStatus === 'complete' && (!data.protocolDone ||
          !(data.readerDone || data.readerAbortedAfterDone) || data.truncated)) ||
        data.status !== 200 || data.contentType !== 'text/event-stream' ||
        typeof data.requestId !== 'number' || !Number.isSafeInteger(data.requestId) || data.requestId < 0 ||
        !Number.isSafeInteger(data.responseChars) || data.responseChars <= 0 || data.responseChars > 100_000) return;

    chrome.runtime.sendMessage({type: 'stream_capture', payload: {
      capture_id: data.attemptId,
      platform: 'chatgpt_web',
      path: data.path,
      request_id: boundedInt(data.requestId, Number.MAX_SAFE_INTEGER),
      status_code: boundedInt(data.status, 599),
      content_type: data.contentType === 'text/event-stream' ? data.contentType : '',
      capture_status: data.captureStatus,
      response_chars: data.responseChars,
      bytes: boundedInt(data.bytes), chunks: boundedInt(data.chunks), frames: boundedInt(data.frames),
      done_markers: boundedInt(data.doneMarkers, 1000),
      protocol_done: data.protocolDone, reader_done: data.readerDone,
      reader_aborted_after_done: data.readerAbortedAfterDone, truncated: data.truncated,
      stream_elapsed_ms: boundedInt(data.streamElapsedMs, 180_000),
      event_types: safeLabels(data.eventTypes), event_shapes: safeLabels(data.eventShapes),
      event_sequence: safeLabels(data.eventSequence),
      observed_at: new Date().toISOString(),
      adapter_version: '0.3.0'
    }}).catch(() => {});
    if (typeof data.text === 'string' && data.text.length === data.responseChars &&
        data.text.length <= 100_000 && typeof CustomEvent === 'function') {
      window.dispatchEvent(new CustomEvent('governanca-ai-network-capture', {detail: {
        attemptId: data.attemptId, requestId: data.requestId,
        text: data.text, captureStatus: data.captureStatus
      }}));
    }
  });
})();
