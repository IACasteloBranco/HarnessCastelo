(() => {
  const marker = 'governanca-ai-prompt-block-v1';
  const policyAttribute = 'data-governanca-block-prompts';
  const untilAttribute = 'data-governanca-allow-until';
  const destination = 'not_approved';
  const protocolVersion = 1;
  const platform = globalThis.GovernancaPlatform;
  const messages = globalThis.GovernancaPolicyMessages || {
    primary: () => 'ENGINE', describe: () => 'Envio retido: não foi possível mostrar o motivo da política.'
  };
  let manualBlocked = null;
  let policySynchronized = false;
  let workerCompatible = false;
  let mainCompatible = false;
  let compatibilityNoticeShown = false;
  let machineAssigned = false;
  let authExpiresAt = null;
  let policyGeneration = 0;
  let verification = 0;
  let lastAttempt = {at: 0, text: '', attachments: '', action: ''};
  let pendingRegeneration = null;
  let replayingMenuItem = null;
  let replayingPrompt = null;
  let inspectionPending = false;

  function resetGrant() {
    const root = document.documentElement;
    root?.setAttribute(policyAttribute, 'block');
    root?.removeAttribute(untilAttribute);
  }
  resetGrant();
  document.addEventListener('readystatechange', resetGrant);

  function verifyMain() {
    const current = ++verification;
    mainCompatible = false;
    policySynchronized = false;
    resetGrant();
    window.postMessage({marker, phase: 'ping'}, location.origin);
    setTimeout(() => {
      if (verification !== current) return;
      reportCompatibilityProblem();
      chrome.runtime.sendMessage({type: 'blocker_health', mainActive: false,
        blocked: manualBlocked !== false, synchronized: policySynchronized,
        machineAssigned, authExpired: authExpiresAt !== null && Date.now() >= authExpiresAt,
        protocolCompatible: false}).catch(() => {});
    }, 1000);
  }
  function connect() {
    try {
      const port = chrome.runtime.connect({name: 'prompt-block-policy'});
      port.onMessage.addListener(message => {
        if (message?.type !== 'block_policy') return;
        policyGeneration++;
        workerCompatible = message.protocolVersion === protocolVersion && message.protocolCompatible === true;
        manualBlocked = message.blocked === true;
        machineAssigned = workerCompatible && message.machineAssigned === true;
        authExpiresAt = Number.isSafeInteger(message.authExpiresAt) ? message.authExpiresAt : null;
        policySynchronized = false;
        resetGrant();
        lastAttempt = {at: 0, text: '', attachments: '', action: ''};
        if (!workerCompatible) reportCompatibilityProblem();
        verifyMain();
      });
      port.onDisconnect.addListener(() => {
        policyGeneration++;
        workerCompatible = false;
        mainCompatible = false;
        manualBlocked = null;
        policySynchronized = false;
        machineAssigned = false;
        authExpiresAt = null;
        resetGrant();
        lastAttempt = {at: 0, text: '', attachments: '', action: ''};
        setTimeout(connect, 1000);
      });
      port.postMessage({type: 'block_status', protocolVersion});
    } catch { setTimeout(connect, 1000); }
  }
  connect();

  chrome.runtime.onMessage?.addListener((message, _sender, reply) => {
    if (message?.type !== 'governanca_probe_policy') return;
    reply({active: true, platform: platform?.claude ? 'claude_web' : 'chatgpt_web'});
  });

  const editor = () => {
    if (platform?.claude) return platform.editor();
    const candidates = [...(document.querySelectorAll?.('#prompt-textarea, [data-testid="prompt-textarea"], form [contenteditable="true"]') || [])];
    return candidates.find(node => !node.getClientRects || node.getClientRects().length) ||
      candidates[0] || document.querySelector('#prompt-textarea') ||
      document.querySelector('[data-testid="prompt-textarea"]') ||
      document.querySelector('form [contenteditable="true"]');
  };
  const editorText = field => field?.innerText || field?.value || field?.textContent || '';

  function showNotice(text, urgent = false) {
    const toast = document.createElement('div');
    toast.textContent = text;
    toast.setAttribute('role', urgent ? 'alert' : 'status');
    toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#182a35;color:white;padding:10px 16px;border-radius:8px;font:14px system-ui;box-shadow:0 2px 12px #0005';
    (document.body || document.documentElement).append(toast);
    setTimeout(() => toast.remove(), 8000);
  }
  function confirmMaskedText(text, categories) {
    return new Promise(resolve => {
      const dialog = document.createElement('dialog');
      dialog.className = 'governanca-mask-dialog';
      dialog.setAttribute('aria-labelledby', 'governanca-preview-title');
      dialog.style.cssText = 'width:min(680px,calc(100vw - 32px));max-height:85vh;overflow:auto;border:1px solid #d6c7a5;border-top:5px solid #c9a86b;border-radius:16px;padding:24px;color:#102f4a;background:#fffdf8;box-shadow:0 20px 64px #102f4a40;font:15px/1.55 "Segoe UI",Arial,sans-serif';
      const title = document.createElement('h2');
      title.id = 'governanca-preview-title'; title.textContent = 'Revise os dados protegidos';
      title.style.cssText = 'margin:0 0 12px;color:#102f4a;font-size:1.3rem;line-height:1.25';
      const detail = document.createElement('p');
      detail.textContent = `Encontramos ${categories.join(', ')}. O envio usará apenas o texto abaixo, com esses dados substituídos.`;
      detail.style.cssText = 'margin:0 0 16px;color:#526579';
      const preview = document.createElement('pre');
      preview.textContent = text;
      preview.style.cssText = 'max-height:45vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f1e8;border:1px solid #e7decd;border-left:4px solid #c9a86b;padding:14px;border-radius:8px;color:#183248;font:14px/1.6 "Segoe UI",Arial,sans-serif';
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;justify-content:flex-end;flex-wrap:wrap;gap:10px;margin-top:18px';
      const cancel = document.createElement('button');
      cancel.className = 'governanca-mask-cancel';
      cancel.type = 'button'; cancel.textContent = 'Voltar e editar';
      cancel.style.cssText = 'min-height:44px;padding:9px 14px;border:1px solid #cbd3d8;border-radius:8px;background:#fff;color:#183248;font:600 14px "Segoe UI",Arial,sans-serif;cursor:pointer';
      const confirm = document.createElement('button');
      confirm.className = 'governanca-mask-confirm';
      confirm.type = 'button'; confirm.textContent = 'Enviar texto mascarado';
      confirm.style.cssText = 'min-height:44px;padding:9px 16px;border:1px solid #102f4a;border-radius:8px;background:#102f4a;color:#fff;font:700 14px "Segoe UI",Arial,sans-serif;cursor:pointer';
      actions.append(cancel, confirm); dialog.append(title, detail, preview, actions);
      const finish = approved => { dialog.close(); dialog.remove(); resolve(approved); };
      cancel.addEventListener('click', () => finish(false));
      confirm.addEventListener('click', () => finish(true));
      dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); }, {once: true});
      (document.body || document.documentElement).append(dialog);
      dialog.showModal();
    });
  }
  function replaceEditorText(field, text) {
    if (!field) return false;
    field.focus();
    if ('value' in field) {
      const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(field, text);
    } else field.textContent = text;
    field.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: null}));
    return editorText(field) === text;
  }
  function replaySend(method, originalTarget) {
    const direct = originalTarget?.closest?.('button');
    const buttons = [...(platform?.composer?.()?.querySelectorAll?.('button') || []),
      ...(document.querySelectorAll?.('button[data-testid="send-button"]') || [])];
    const button = direct && platform?.sendButton?.(direct) ? direct : buttons.find(node => platform?.sendButton?.(node));
    if (button) { button.click(); return true; }
    const form = editor()?.closest?.('form');
    if (form?.requestSubmit) { form.requestSubmit(); return true; }
    return false;
  }
  function reportCompatibilityProblem() {
    policySynchronized = false;
    resetGrant();
    if (compatibilityNoticeShown) return;
    compatibilityNoticeShown = true;
    showNotice('Não foi possível confirmar a versão da extensão. Preserve seu rascunho, recarregue a extensão e esta aba do ChatGPT.', true);
  }
  function logDecision(decision, method) {
    try {
      chrome.runtime.sendMessage({type: 'prompt_decision', action: decision.action,
        version: decision.version, destination, method,
        primaryRule: messages.primary(decision),
        findings: decision.findings.map(item => ({rule: item.rule, action: item.action, count: item.count}))
      }).catch(() => {});
    } catch {}
  }
  function evaluate(text) {
    let decision;
    try {
      decision = policySynchronized
        ? globalThis.GovernancaPromptPolicy?.evaluate(text, {destination})
        : {version: '0.1.2', action: 'BLOCK', findings: [{rule: 'SYNC', action: 'BLOCK', count: 1}]};
      if (!decision) throw new Error('Política indisponível');
    } catch {
      decision = {version: '0.1.2', action: 'REVIEW', findings: [{rule: 'ENGINE', action: 'REVIEW', count: 1}]};
    }
    if (manualBlocked === true) decision = {...decision, action: 'BLOCK',
      findings: [...decision.findings, {rule: 'MANUAL', action: 'BLOCK', count: 1}]};
    if (!machineAssigned || (authExpiresAt !== null && Date.now() >= authExpiresAt))
      decision = {...decision, action: 'BLOCK',
        findings: [...decision.findings, {rule: 'MACHINE', action: 'BLOCK', count: 1}]};
    return decision;
  }
  function stop(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
  function inspect(event, method, textOverride, turnKey, retryMenuItem) {
    const text = (textOverride ?? editorText(editor())).trim();
    const fileRoot = platform?.fileRoot?.() || platform?.composer() || editor()?.closest?.('form');
    const attachments = method === 'regenerate' ? null : globalThis.GovernancaFiles?.observe(fileRoot);
    if ((!replayingPrompt || replayingPrompt.text !== text || Date.now() - replayingPrompt.at >= 5000) && text) {
      stop(event);
      if (inspectionPending) return;
      inspectionPending = true;
      chrome.runtime.sendMessage({type: 'inspect_sensitive_text', text: textOverride ?? editorText(editor())})
        .then(async result => {
          if (result?.action === 'block') {
            showNotice('Envio bloqueado pela política de proteção de dados.', true);
            return;
          }
          if (result?.action === 'mask') {
            if (method === 'regenerate') {
              showNotice('Este turno contém dados que precisam ser mascarados. Reenvie o texto pelo compositor para revisar a prévia.', true);
              return;
            }
            if (editorText(editor()).trim() !== text) {
              showNotice('O rascunho mudou durante a inspeção. Envie novamente para revisar o texto atualizado.', true);
              return;
            }
            if (!await confirmMaskedText(result.text, result.categories)) return;
            const field = editor();
            if (editorText(field).trim() !== text || !replaceEditorText(field, result.text)) {
              showNotice('Não foi possível atualizar o compositor com o texto mascarado. Revise e tente novamente.', true);
              return;
            }
          } else if (result?.action !== 'allow') {
            showNotice('Inspeção indisponível. O envio foi bloqueado; tente novamente.', true);
            return;
          }
          const replay = {text: editorText(editor()).trim(), at: Date.now()};
          replayingPrompt = replay;
          if (method === 'regenerate') {
            replay.text = text;
            inspect({preventDefault() {}, stopImmediatePropagation() {}}, method, text, turnKey, retryMenuItem);
            Promise.resolve().then(() => { if (replayingPrompt === replay) replayingPrompt = null; });
            return;
          }
          if (!replaySend(method, event.target)) {
            replayingPrompt = null;
            showNotice('Não foi possível retomar o envio. Use o botão Enviar novamente.', true);
          } else Promise.resolve().then(() => { if (replayingPrompt === replay) replayingPrompt = null; });
        }).catch(() => {
          showNotice('Inspeção indisponível. O envio foi bloqueado; tente novamente quando o serviço voltar.', true);
        }).finally(() => { inspectionPending = false; });
      return;
    }
    if (!text && !(attachments?.capture_status === 'observed' && attachments.items.length)) return;
    const now = Date.now();
    const attachmentKey = JSON.stringify(attachments?.items || []);
    // shortcut: identical prompt and attachment metadata within 500 ms share one capture; widen only if repeated rapid submits must be distinct.
    if (now - lastAttempt.at < 500 && text === lastAttempt.text && attachmentKey === lastAttempt.attachments) {
      if (lastAttempt.action === 'BLOCK' || lastAttempt.action === 'REVIEW') stop(event);
      return;
    }
    resetGrant();
    const decision = evaluate(text);
    lastAttempt = {at: now, text, attachments: attachmentKey, action: decision.action, method};
    logDecision(decision, method);
    if (decision.action === 'BLOCK' || decision.action === 'REVIEW') {
      stop(event);
      showNotice(messages.describe(decision), true);
      return;
    }
    if (method === 'regenerate') {
      stop(event);
      Promise.resolve(globalThis.GovernancaCaptureRegeneration?.(text, turnKey)).then(ready => {
        if (ready !== true || !retryMenuItem?.isConnected) {
          resetGrant();
          showNotice('Regeneração indisponível para este turno. Envie o prompt novamente no editor.', true);
          return;
        }
        document.documentElement?.setAttribute(policyAttribute, 'allow');
        document.documentElement?.setAttribute(untilAttribute, String(Math.min(Date.now() + 15000,
          authExpiresAt ?? Infinity)));
        replayingMenuItem = retryMenuItem;
        retryMenuItem.click();
      }).catch(() => {
        resetGrant();
        showNotice('Não foi possível localizar a interação salva para este turno.', true);
      });
      if (decision.action === 'WARN') showNotice(messages.describe(decision));
      return;
    }
    document.documentElement?.setAttribute(policyAttribute, 'allow');
    document.documentElement?.setAttribute(untilAttribute, String(Math.min(
      now + (attachments?.capture_status === 'observed' ? 120000 : 15000), authExpiresAt ?? Infinity)));
    globalThis.GovernancaCaptureAttempt?.(attachments);
    if (decision.action === 'WARN')
      showNotice(messages.describe(decision));
  }

  window.addEventListener('click', event => {
    const menuItem = event.target?.closest?.('[role="menuitem"]');
    if (menuItem && menuItem === replayingMenuItem) { replayingMenuItem = null; return; }
    const retry = /^(Tentar novamente|Try again)(?:\s|$)/i.test(menuItem?.textContent || '');
    if (menuItem?.getAttribute?.('role') === 'menuitem' && (pendingRegeneration || retry)) {
      const pending = pendingRegeneration;
      pendingRegeneration = null;
      if (pending && Date.now() - pending.at <= 30_000 && retry)
        inspect(event, 'regenerate', pending.text, pending.turnKey, menuItem);
      else {
        stop(event);
        showNotice(retry ? 'Regeneração indisponível para este turno. Envie o prompt novamente no editor.'
          : 'Este modo de regeneração ainda não é suportado.', true);
      }
      return;
    }
    const button = event.target?.closest?.('button');
    if (/^(Gerar resposta novamente|Regenerate response)$/.test(button?.getAttribute?.('aria-label') || '')) {
      const turn = button.closest?.('[data-turn-key]');
      const user = turn?.querySelector?.('[data-content-search-unit-key$=":user"], [data-message-author-role="user"]');
      const text = (user?.innerText || user?.textContent || '').trim();
      const turnKey = turn?.getAttribute?.('data-turn-key');
      pendingRegeneration = text && turnKey ? {text, turnKey, at: Date.now()} : null;
      return;
    }
    pendingRegeneration = null;
    const form = editor()?.closest?.('form');
    if (platform?.claude ? platform.sendButton(button) : (button?.matches?.('button[data-testid="send-button"]') ||
        (form?.contains(button) && (button?.type === 'submit' ||
          /^(Enviar|Send)$/.test(button?.getAttribute?.('aria-label') || ''))))) inspect(event, 'click');
  }, true);
  window.addEventListener('keydown', event => {
    const field = editor();
    const inEditor = field && (field.contains(event.target) || event.composedPath?.().includes(field));
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && inEditor)
      inspect(event, 'enter');
  }, true);
  window.addEventListener('submit', event => {
    if (editor()?.closest?.('form') === event.target) inspect(event, 'submit');
  }, true);
  window.addEventListener('message', event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.marker !== marker) return;
    if (event.data.phase === 'backend_preflight' &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(event.data.requestId || '')) {
      const generation = policyGeneration;
      if (event.data.protocolVersion !== protocolVersion) {
        window.postMessage({marker, phase: 'backend_preflight_result', requestId: event.data.requestId,
          protocolVersion, available: false, reason: 'extension_mismatch'}, location.origin);
        return;
      }
      const policyAllows = () => policySynchronized && manualBlocked !== true && machineAssigned &&
        (authExpiresAt === null || Date.now() < authExpiresAt);
      if (!policyAllows()) {
        window.postMessage({marker, phase: 'backend_preflight_result', requestId: event.data.requestId,
          protocolVersion, available: false, reason: 'capture_unavailable'}, location.origin);
        return;
      }
      chrome.runtime.sendMessage({type: 'backend_preflight', protocolVersion}).then(result => {
        const stillAllowed = generation === policyGeneration && policyAllows();
        const responseCompatible = result?.ok === true && result.data?.protocolVersion === protocolVersion;
        const available = stillAllowed && responseCompatible && result.data?.available === true;
        const reason = available ? null : !stillAllowed ? 'capture_unavailable' :
          !responseCompatible ? result?.ok === true ? 'extension_mismatch' : 'extension_unavailable'
            : result.data?.reason || 'backend_unavailable';
        if (reason === 'extension_mismatch' || reason === 'extension_unavailable') reportCompatibilityProblem();
        window.postMessage({marker, phase: 'backend_preflight_result', requestId: event.data.requestId,
          protocolVersion, available, reason}, location.origin);
      }).catch(() => {
        reportCompatibilityProblem();
        window.postMessage({marker, phase: 'backend_preflight_result', requestId: event.data.requestId,
          protocolVersion, available: false, reason: 'extension_unavailable'}, location.origin);
      });
      return;
    }
    if (event.data.phase === 'network_blocked') {
      const reason = ['expired', 'backend_unavailable', 'capture_unavailable',
        'extension_mismatch', 'extension_unavailable'].includes(event.data.reason)
        ? event.data.reason : 'missing';
      chrome.runtime.sendMessage({type: 'prompt_blocked', method: 'network', reason}).catch(() => {});
      if (reason === 'backend_unavailable') {
        showNotice('Envio impedido: o backend de governança não respondeu. O prompt continua no compositor; tente novamente quando o serviço voltar.', true);
        return;
      }
      if (reason === 'capture_unavailable') {
        showNotice('Envio impedido: captura ou atribuição da extensão está pausada. Verifique o login e a atribuição desta instalação.', true);
        return;
      }
      if (reason === 'extension_mismatch' || reason === 'extension_unavailable') {
        reportCompatibilityProblem();
        return;
      }
      // shortcut: use the current composer for any rejected conversation POST; narrow if other automatic sends need separate treatment.
      const text = editorText(editor()).trim();
      if (text) {
        const decision = evaluate(text);
        logDecision(decision, 'network');
        if (decision.action === 'BLOCK' || decision.action === 'REVIEW') {
          showNotice(messages.describe(decision), true);
          return;
        }
        showNotice(`${messages.describe(decision)} O prompt continua no compositor; revise e use Enviar.`);
        return;
      }
      showNotice(reason === 'expired' ? 'Envio impedido: o tempo para processar o anexo expirou. Tente enviar novamente.'
        : 'Envio impedido: não havia uma decisão válida para este prompt.');
    }
    if (event.data.phase === 'pong') {
      verification++;
      mainCompatible = event.data.protocolVersion === protocolVersion;
      policySynchronized = workerCompatible && mainCompatible;
      if (policySynchronized) compatibilityNoticeShown = false;
      else reportCompatibilityProblem();
      chrome.runtime.sendMessage({type: 'blocker_health', mainActive: true,
        blocked: manualBlocked !== false, synchronized: policySynchronized,
        machineAssigned, authExpired: authExpiresAt !== null && Date.now() >= authExpiresAt,
        mainBlocked: event.data.blocked === true, protocolCompatible: policySynchronized}).catch(() => {});
    }
  });
})();
