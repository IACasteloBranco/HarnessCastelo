(() => {
  const limit = 20;
  const selectionTtl = 120_000;
  const selections = [];
  const lastFileLists = new WeakMap();
  const watchedInputs = new WeakSet();
  const observationSelections = new WeakMap();
  let selectionRoute = null;
  let inputObserver = null;
  let pasteListenerInstalled = false;
  const unavailable = () => ({capture_status: 'unavailable', items: [], truncated: false});
  const currentRoute = () => globalThis.location?.pathname || '';

  function syncRoute() {
    const route = currentRoute();
    if (selectionRoute !== route) {
      selections.length = 0;
      selectionRoute = route;
    }
  }

  function fileMetadata(file) {
    const rawName = typeof file?.name === 'string' ? file.name.trim() : '';
    const name = rawName && rawName.length <= 512 && !/[\\/\u0000-\u001f\u007f]/.test(rawName)
      ? rawName : null;
    const rawMime = typeof file?.type === 'string' ? file.type.trim().toLowerCase() : '';
    const mime_type = /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/.test(rawMime) && rawMime.length <= 255
      ? rawMime : null;
    const size_bytes = Number.isSafeInteger(file?.size) && file.size >= 0 ? file.size : null;
    return {name, mime_type, size_bytes,
      capture_status: name || mime_type || size_bytes !== null ? 'metadata_only' : 'presence_only',
      source: 'selection_event'};
  }

  function visibleCardMetadata(button) {
    const rawName = button?.getAttribute?.('aria-label')?.trim() || '';
    if (!rawName || /^(?:remover|remove)\s/i.test(rawName)) return null;
    const name = rawName.length <= 512 && !/[\\/\u0000-\u001f\u007f]/.test(rawName) ? rawName : null;
    return name ? {name, mime_type: null, size_bytes: null,
      capture_status: 'metadata_only', source: 'visible_card'} : null;
  }

  function rememberSelection(input, fileList = input?.files) {
    syncRoute();
    if (!fileList?.length) return;
    const now = Date.now();
    const previous = lastFileLists.get(input);
    if (previous?.fileList === fileList && now - previous.capturedAt < 1000) return;
    lastFileLists.set(input, {fileList, capturedAt: now});
    const selected = [...fileList].map(file => ({metadata: fileMetadata(file), capturedAt: now}));
    selections.push(...selected);
    selections.splice(0, selections.length - limit);
  }

  function rememberPaste(event) {
    const clipboard = event.clipboardData;
    const items = [...(clipboard?.items || [])];
    const files = clipboard?.files?.length ? clipboard.files :
      items.filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
    rememberSelection(event, files);
  }

  function rememberDrop(event) {
    rememberSelection(event, event.dataTransfer?.files);
  }

  function watchFileInput(input) {
    if (!input?.matches?.('input[type="file"]') || watchedInputs.has(input)) return;
    watchedInputs.add(input);
    const remember = () => rememberSelection(input);
    input.addEventListener('input', remember, true);
    input.addEventListener('change', remember, true);
  }

  function watchFileInputs(root) {
    if (!root?.querySelectorAll) return;
    for (const input of root.querySelectorAll('input[type="file"]')) watchFileInput(input);
  }

  function watchDocument() {
    const document = globalThis.document;
    const root = document?.documentElement;
    if (!root) return;
    watchFileInputs(root);
    if (!pasteListenerInstalled && document.addEventListener) {
      document.addEventListener('paste', rememberPaste, true);
      document.addEventListener('drop', rememberDrop, true);
      pasteListenerInstalled = true;
    }
    if (inputObserver || typeof globalThis.MutationObserver !== 'function') return;
    inputObserver = new MutationObserver(records => {
      for (const record of records) for (const node of record.addedNodes || []) {
        watchFileInput(node);
        watchFileInputs(node);
      }
    });
    inputObserver.observe(root, {childList: true, subtree: true});
  }

  if (globalThis.document?.documentElement) watchDocument();
  else globalThis.document?.addEventListener('readystatechange', watchDocument);

  function observe(root) {
    syncRoute();
    if (!root?.querySelectorAll) return unavailable();
    const cutoff = Date.now() - selectionTtl;
    for (let index = selections.length - 1; index >= 0; index--)
      if (selections[index].capturedAt < cutoff) selections.splice(index, 1);
    const inputs = [...root.querySelectorAll('input[type="file"]')];
    const files = inputs.flatMap(input => [...(input.files || [])]);
    const cards = [...root.querySelectorAll('[data-composer-attachments] button[aria-label]')]
      .map(visibleCardMetadata).filter(Boolean);
    const items = files.map(fileMetadata);
    const candidatesByName = new Map();
    for (const selection of selections) {
      const name = selection.metadata.name;
      if (!name) continue;
      const matches = candidatesByName.get(name) || [];
      matches.push(selection);
      candidatesByName.set(name, matches);
    }
    const inputCounts = new Map();
    for (const item of items) if (item.name)
      inputCounts.set(item.name, (inputCounts.get(item.name) || 0) + 1);
    const cardCounts = new Map();
    for (const card of cards)
      cardCounts.set(card.name, (cardCounts.get(card.name) || 0) + 1);
    const used = new Set();
    for (const card of cards) {
      const inputCount = inputCounts.get(card.name) || 0;
      if (inputCount) {
        inputCounts.set(card.name, inputCount - 1);
        const cached = candidatesByName.get(card.name)?.shift();
        if (cached) used.add(cached);
        continue;
      }
      const exactCandidates = candidatesByName.get(card.name);
      const originalName = card.name.replace(/\((?:\d+|\d{8}-\d{6})\)(?=\.[^.]+$|$)/, '');
      const candidates = exactCandidates?.length ? exactCandidates : candidatesByName.get(originalName) || [];
      if (candidates.length === 1 && cardCounts.get(card.name) === 1) {
        const selected = candidates[0];
        items.push(selected.metadata);
        used.add(selected);
        continue;
      }
      if (candidates.length) {
        items.push({...card, association_status: 'ambiguous'});
        for (const selected of candidates) used.add(selected);
      } else items.push(card);
    }
    if (!inputs.length && !cards.length) return unavailable();
    const observation = {capture_status: items.length ? 'observed' : 'not_observed',
      items: items.slice(0, limit), truncated: items.length > limit};
    observationSelections.set(observation, used);
    return observation;
  }

  function consume(observation) {
    syncRoute();
    const used = observationSelections.get(observation);
    if (!used) return;
    const consumed = new Set(used);
    const remaining = selections.filter(item => !consumed.has(item));
    selections.splice(0, selections.length, ...remaining);
    observationSelections.delete(observation);
  }

  globalThis.GovernancaFiles = {observe, rememberSelection, consume};
})();
