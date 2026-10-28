(() => {
  const installed = Symbol.for('governanca.ai.prompt.block.v1');
  if (window[installed]) return;
  window[installed] = true;
  if (typeof window.fetch !== 'function') return;
  const originalFetch = window.fetch;
  const marker = 'governanca-ai-prompt-block-v1';
  const protocolVersion = 1;
  const conversationPath = /^\/backend-api\/(?:[^/]+\/)*conversation\/?$/;
  const claudeCompletionPath = /^\/api\/organizations\/[^/]+\/chat_conversations\/[^/]+\/completion\/?$/;
  const pendingPreflights = new Map();

  function requestBackendPreflight(signal) {
    if (signal?.aborted) return Promise.resolve('cancelled');
    if (pendingPreflights.size >= 8) return Promise.resolve('extension_unavailable');
    const requestId = crypto.randomUUID();
    return new Promise(resolve => {
      const finish = outcome => {
        const pending = pendingPreflights.get(requestId);
        if (!pending) return;
        clearTimeout(pending.timeout);
        signal?.removeEventListener('abort', pending.abort);
        pendingPreflights.delete(requestId);
        resolve(outcome);
      };
      const abort = () => finish('cancelled');
      const timeout = setTimeout(() => finish('extension_unavailable'), 11_000);
      pendingPreflights.set(requestId, {finish, timeout, abort});
      signal?.addEventListener('abort', abort, {once: true});
      if (signal?.aborted) { abort(); return; }
      window.postMessage({marker, phase: 'backend_preflight', requestId, protocolVersion}, location.origin);
    });
  }

  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin ||
        event.data?.marker !== marker) return;
    if (event.data.phase === 'backend_preflight_result') {
      const outcome = event.data.protocolVersion !== protocolVersion ? 'extension_mismatch' :
        event.data.available === true ? 'available' :
        ['capture_unavailable', 'backend_unavailable', 'extension_mismatch', 'extension_unavailable']
          .includes(event.data.reason) ? event.data.reason : 'backend_unavailable';
      pendingPreflights.get(event.data.requestId)?.finish(outcome);
      return;
    }
    if (event.data.phase === 'ping') window.postMessage({marker, phase: 'pong', protocolVersion, blocked:
      document.documentElement?.getAttribute('data-governanca-block-prompts') !== 'allow'}, location.origin);
  });
  window.fetch = new Proxy(originalFetch, {
    apply(target, thisArg, args) {
      let candidate = false;
      const input = args[0];
      try {
        const url = new URL(typeof input === 'string' ? input : input?.url || String(input), location.href);
        const method = String(args[1]?.method || input?.method || 'GET').toUpperCase();
        candidate = url.origin === location.origin && method === 'POST' &&
          (location.origin === 'https://claude.ai' ? claudeCompletionPath : conversationPath).test(url.pathname);
      } catch { /* Deixar a própria aplicação tratar entradas inválidas. */ }
      if (!candidate) return Reflect.apply(target, thisArg, args);
      const root = document.documentElement;
      const allowed = root?.getAttribute('data-governanca-block-prompts') === 'allow';
      const expiresAt = Number(root?.getAttribute('data-governanca-allow-until'));
      const validGrant = allowed && Date.now() <= expiresAt;
      if (validGrant) {
        root.setAttribute('data-governanca-block-prompts', 'block');
        root.removeAttribute('data-governanca-allow-until');
        const signal = args[1]?.signal || input?.signal;
        return requestBackendPreflight(signal).then(outcome => {
          if (outcome === 'available' && !signal?.aborted) return Reflect.apply(target, thisArg, args);
          if (outcome === 'cancelled' || signal?.aborted) throw new DOMException('Envio cancelado.', 'AbortError');
          const reason = ['capture_unavailable', 'extension_mismatch', 'extension_unavailable'].includes(outcome)
            ? outcome : 'backend_unavailable';
          try { window.postMessage({marker, phase: 'network_blocked', reason}, location.origin); } catch { /* diagnóstico opcional */ }
          throw new DOMException('Envio bloqueado: pré-condição de Governança IA indisponível.', 'AbortError');
        });
      }
      try { window.postMessage({marker, phase: 'network_blocked', reason: allowed && Date.now() > expiresAt ? 'expired' : 'missing'}, location.origin); } catch { /* diagnóstico opcional */ }
      return Promise.reject(new DOMException('Envio bloqueado pela Governança IA.', 'AbortError'));
    }
  });
})();
