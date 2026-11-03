(() => {
  const attempts = new Map();
  const recent = [];
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const promptCaptureAttribute = 'data-governanca-prompt-capture';
  const platform = globalThis.GovernancaPlatform;
  const editor = () => platform?.editor?.() || [...document.querySelectorAll('#prompt-textarea, [data-testid="prompt-textarea"], form [contenteditable="true"]')]
    .find(node => !node.getClientRects || node.getClientRects().length);

  chrome.runtime.onMessage?.addListener((message, _sender, reply) => {
    if (platform?.claude && message?.type === 'probe_status')
      reply({active: true, adapterVersion: '0.4.6'});
    if (platform?.claude && message?.type === 'probe_config')
      window.postMessage({marker: 'governanca-ai-claude-network-v1', phase: 'capture_config',
        enabled: message.enabled === true}, location.origin);
  });

  if (platform?.claude) chrome.runtime.sendMessage({type: 'probe_config'}).then(result => {
    if (result?.ok) window.postMessage({marker: 'governanca-ai-claude-network-v1', phase: 'capture_config',
      enabled: result.data?.enabled === true}, location.origin);
  }).catch(() => {});

  async function send(message) {
    const result = await chrome.runtime.sendMessage(message);
    if (!result?.ok) throw new Error(result?.error || 'Falha na captura.');
    return result.data;
  }

  async function promptHash(text) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text.trim()));
    return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function turnForPrompt(text) {
    const matches = [...document.querySelectorAll('[data-turn-key]')].filter(turn => {
      const user = turn.querySelector('[data-content-search-unit-key$=":user"], [data-message-author-role="user"]');
      return (user?.innerText || user?.textContent || '').trim() === text.trim();
    });
    return matches.length === 1 ? matches[0] : null;
  }

  function markAttempt(state) {
    const attemptId = crypto.randomUUID();
    state.delivered = false;
    attempts.set(attemptId, state);
    if (attempts.size > 8) attempts.delete(attempts.keys().next().value);
    document.documentElement.setAttribute('data-governanca-probe-attempt', attemptId);
    document.documentElement.setAttribute('data-governanca-probe-until', String(Date.now() + 120_000));
    return attemptId;
  }

  globalThis.GovernancaCaptureAttempt = attachmentObservation => {
    const field = editor();
    const text = field?.innerText || field?.value || field?.textContent || '';
    const observation = attachmentObservation || {capture_status: 'unavailable', items: [], truncated: false};
    const hasAttachments = observation.capture_status === 'observed' && observation.items?.length > 0;
    if ((!text.trim() && !hasAttachments) || text.length > 100_000) return;
    const observedAt = new Date().toISOString();
    const url = location.origin + location.pathname;
    const conversationMatch = platform?.claude
      ? location.pathname.match(/^\/chat\/([^/]+)\/?$/)
      : location.pathname.match(/^\/(?:g\/[a-zA-Z0-9-]+\/)?c\/([^/]+)\/?$/);
    const conversation = conversationMatch && UUID.test(conversationMatch[1])
      ? {url, capture_status: 'observed'}
      : {capture_status: 'unknown', reason: 'ID da conversa indisponível no momento do envio'};
    const project = /^\/g\/g-p-[a-zA-Z0-9]+(?:\/|$)/.test(location.pathname)
      ? {url, capture_status: 'observed'}
      : {capture_status: 'unknown', reason: 'Projeto não identificado na URL'};
    const state = {promptText: text, conversationUrl: url, platform: platform?.claude ? 'claude_web' : 'chatgpt_web',
      priorUserCount: platform?.claude ? platform.messages().filter(node => platform.role(node) === 'user').length : 0,
      confirmed: false};
    state.promptHash = promptHash(text);
    const attemptId = markAttempt(state);
    document.documentElement.setAttribute(promptCaptureAttribute, 'pending');
    recent.push(state);
    if (recent.length > 8) recent.shift();
    state.interaction = send({type: 'capture_prompt', payload: {
      schema_version: '0.1', client_event_id: attemptId, platform: state.platform,
      project, conversation,
      prompt: {text, capture_status: 'observed'},
      attachments: observation.items || [], attachments_capture_status: observation.capture_status,
      attachments_truncated: observation.truncated === true,
      adapter_version: '0.4.6', observed_at: observedAt
    }}).then(result => {
      document.documentElement.setAttribute(promptCaptureAttribute, 'stored');
      globalThis.GovernancaFiles?.consume?.(observation);
      return result.interaction_id;
    });
    state.interaction.catch(() => {
      document.documentElement.setAttribute(promptCaptureAttribute, 'rejected');
      attempts.delete(attemptId);
      const index = recent.indexOf(state);
      if (index >= 0) recent.splice(index, 1);
      console.warn('[Governança IA] Prompt sem confirmação no backend.');
    });
    return attemptId;
  };

  globalThis.GovernancaCaptureRegeneration = async (text, turnKey) => {
    if (platform?.claude) return false;
    if (typeof text !== 'string' || !text.trim()) return false;
    const url = location.origin + location.pathname;
    if (!UUID.test(turnKey || '')) return false;
    const matches = recent.filter(item => item.confirmed && item.conversationUrl === url &&
      item.turnKey === turnKey && item.promptText.trim() === text.trim());
    const linked = matches.length === 1 ? {interaction_id: await matches[0].interaction,
      prompt_hash: await matches[0].promptHash} :
      await send({type: 'lookup_turn', conversationUrl: url, turnKey});
    if (!linked?.interaction_id || linked.prompt_hash !== await promptHash(text)) return false;
    markAttempt({interaction: Promise.resolve(linked.interaction_id), promptText: text,
      promptHash: Promise.resolve(linked.prompt_hash), turnKey, conversationUrl: url});
    return true;
  };

  function deliverResponse(attemptId, text, captureStatus) {
    const state = attempts.get(attemptId);
    if (!UUID.test(attemptId || '') || !state || state.delivered ||
        typeof text !== 'string' || !text || text.length > 100_000 ||
        !['complete', 'incomplete'].includes(captureStatus)) return;
    state.delivered = true;
    void state.interaction.then(interactionId => send({type: 'capture_response', interactionId,
      payload: {client_event_id: attemptId, text, capture_status: captureStatus,
        observed_at: new Date().toISOString(), adapter_version: '0.4.6'}
    })).then(async () => {
      state.confirmed = true;
      state.conversationUrl = location.origin + location.pathname;
      if (state.platform === 'claude_web') return;
      const turn = turnForPrompt(state.promptText);
      const turnKey = turn?.getAttribute('data-turn-key');
      if (turnKey) {
        state.turnKey = turnKey;
        await send({type: 'remember_turn', conversationUrl: state.conversationUrl,
          turnKey, interactionId: await state.interaction, promptHash: await state.promptHash});
      }
    }).catch(() => console.warn('[Governança IA] Resposta sem confirmação no backend.'))
      .finally(() => {
        if (state.responseTimer) clearTimeout(state.responseTimer);
        attempts.delete(attemptId);
      });
  }

  function claudeResponse(state) {
    const nodes = platform.messages();
    let userCount = nodes.filter(node => platform.role(node) === 'user').length;
    for (let index = nodes.length - 1; index >= 0; index--) {
      const node = nodes[index];
      if (platform.role(node) !== 'user') continue;
      const ordinal = --userCount;
      const text = node.innerText || node.textContent || '';
      if (ordinal < state.priorUserCount || (state.promptText.trim() && text.trim() !== state.promptText.trim())) continue;
      return nodes.slice(index + 1).find(item => platform.role(item) === 'assistant') || null;
    }
    return null;
  }

  function observeClaudeResponses() {
    if (!platform?.claude) return;
    for (const [attemptId, state] of attempts) {
      if (state.platform !== 'claude_web' || state.delivered) continue;
      const response = claudeResponse(state);
      const text = response ? platform.responseText(response) : '';
      if (!text || text.length > 100_000) continue;
      if (platform.streaming()) {
        if (state.responseTimer) clearTimeout(state.responseTimer);
        state.responseTimer = null;
        continue;
      }
      if (state.responseTimer) clearTimeout(state.responseTimer);
      // shortcut: stable rendered text plus a missing stop control estimates completion; upgrade if Claude exposes a reliable terminal signal.
      state.responseTimer = setTimeout(() => {
        const latest = claudeResponse(state);
        const finalText = latest ? platform.responseText(latest) : '';
        if (state.delivered || platform.streaming() || finalText !== text) {
          observeClaudeResponses();
          return;
        }
        deliverResponse(attemptId, state.networkText === finalText ? state.networkText : finalText,
          state.stopRequested ? 'incomplete' : 'complete');
      }, 800);
    }
  }

  if (platform?.claude && typeof MutationObserver === 'function') {
    const start = () => {
      if (!document.documentElement || start.observer) return;
      start.observer = new MutationObserver(observeClaudeResponses);
      start.observer.observe(document.documentElement, {childList: true, subtree: true, characterData: true});
    };
    start();
    document.addEventListener('DOMContentLoaded', start, {once: true});
    window.addEventListener('click', event => {
      const button = event.target?.closest?.('button');
      if (platform.stopButton(button)) {
        for (const state of attempts.values()) {
          if (state.platform === 'claude_web') state.stopRequested = true;
        }
      }
    }, true);
  }

  window.addEventListener('governanca-ai-network-capture', event => {
    const {attemptId, text, captureStatus} = event.detail || {};
    deliverResponse(attemptId, text, captureStatus);
  });

  if (platform?.claude) window.addEventListener('message', event => {
    const data = event.data;
    if (event.source !== window || event.origin !== location.origin ||
        data?.marker !== 'governanca-ai-claude-network-v1' || data.phase !== 'assistant_text' ||
        !UUID.test(data.attemptId || '') || typeof data.text !== 'string' || !data.text || data.text.length > 100_000) return;
    const state = attempts.get(data.attemptId);
    if (!state || state.platform !== 'claude_web' || state.delivered) return;
    state.networkText = data.text;
    observeClaudeResponses();
  });
})();
