(() => {
  const claude = new URL(location.href).origin === 'https://claude.ai';
  const visible = node => !node?.getClientRects || node.getClientRects().length > 0;
  const editor = () => {
    const known = [...document.querySelectorAll(
    claude ? '[contenteditable="true"].ProseMirror, [data-testid="chat-input"] [contenteditable="true"]'
      : '#prompt-textarea, [data-testid="prompt-textarea"], form [contenteditable="true"]'
    )].find(visible);
    if (known || !claude) return known || null;
    const candidates = [...document.querySelectorAll('[contenteditable="true"], textarea')]
      .filter(node => visible(node) && !node.disabled && !node.readOnly &&
        !node.closest?.('pre, code, .monaco-editor, .cm-editor, [data-artifact-id]'));
    // A unique editable field is safe to recognize without a provider CSS class.
    return candidates.length === 1 ? candidates[0] : null;
  };
  const composer = () => {
    const field = editor();
    const known = field?.closest?.('form') || (claude ? field?.closest?.('[data-testid="chat-input"]') : null);
    if (known || !claude) return known;
    // Claude can render the composer without a form. Keep the search local.
    let parent = field?.parentElement;
    for (let depth = 0; parent && depth < 6; depth++, parent = parent.parentElement) {
      if (parent.matches?.('main, body, html')) break;
      if ([...(parent.querySelectorAll?.('button') || [])].some(node =>
        /^(Send|Send message|Enviar|Enviar mensagem|Stop response|Stop generating|Parar|Interromper resposta)$/i.test(label(node)))) return parent;
    }
    return null;
  };
  const fileRoot = () => {
    const base = composer();
    if (!claude || !base) return base;
    let parent = base.parentElement;
    for (let depth = 0; parent && depth < 3; depth++, parent = parent.parentElement) {
      if (parent.matches?.('main, body, html, [data-testid="user-message"], [data-testid="assistant-message"]')) break;
      const preview = [...(parent.querySelectorAll?.('[data-file-name], [data-testid="attachment"], [data-testid="file-upload"], [data-testid="file-thumbnail"], img[src^="blob:"], img[alt$=".png" i], img[alt$=".jpg" i], img[alt$=".jpeg" i], img[alt$=".webp" i], .cds-card-body img') || [])]
        .some(node => !node.closest?.('[data-testid="user-message"], [data-testid="assistant-message"], .font-claude-response'));
      if (preview) return parent;
    }
    return base;
  };
  const label = node => (node?.getAttribute?.('aria-label') || '').trim();
  const sendButton = node => Boolean(node && visible(node) && !stopButton(node) && (
    node.matches?.('button[data-testid="send-button"]') ||
    (claude && /^(Send message|Enviar mensagem)$/i.test(label(node))) ||
    (composer()?.contains(node) && ((node.type === 'submit' && editor()?.closest?.('form')?.contains(node)) || /^(Send|Enviar)$/i.test(label(node))))));
  const stopButton = node => Boolean(node && visible(node) && (
    node.matches?.('button[data-testid="stop-button"]') ||
    /^(Stop|Parar|Stop generating|Stop response|Interromper resposta)$/i.test(label(node))));
  const role = node => node?.matches?.('[data-testid="user-message"]') ? 'user'
    : node?.matches?.('.font-claude-response, [data-testid="assistant-message"]') ? 'assistant' : null;
  const responseText = node => {
    const content = node?.matches?.('.font-claude-response') ? node
      : node?.querySelector?.('.font-claude-response') || node;
    const markdownSelector = '.standard-markdown, [data-testid="markdown"], [data-testid="response-content"]';
    const markdown = content?.matches?.(markdownSelector) ? [content]
      : [...(content?.querySelectorAll?.(markdownSelector) || [])];
    const roots = markdown.length ? [...markdown] : content ? [content] : [];
    const excluded = [
      'button', '[role="button"]', '[aria-hidden="true"]', '[aria-label]', 'time',
      '[class~="sr-only"]', '[class~="visually-hidden"]',
      '[data-testid*="action"]', '[data-testid*="feedback"]', '[data-testid*="copy"]'
    ];
    // Claude may render code blocks in a sibling wrapper outside the selected
    // Markdown node. Include only semantic pre/code blocks still inside this
    // response, never neighboring message or action chrome.
    if (markdown.length && content) {
      const codeBlocks = [...(content.querySelectorAll?.('pre') || [])].filter(pre =>
        !markdown.some(root => root === pre || root.contains?.(pre)) &&
        !pre.closest?.(excluded.join(',')));
      roots.push(...codeBlocks);
    }
    const serialize = node => {
      if (node?.nodeType === 3) return node.nodeValue || '';
      if (node?.nodeType !== 1) return [...(node?.childNodes || [])].map(serialize).join('');
      if (node.matches?.(excluded.join(','))) return '';
      const tag = node.tagName?.toLowerCase();
      const children = [...(node.childNodes || [])].map(serialize).join('');
      if (/^h[1-6]$/.test(tag || '')) return `\n${'#'.repeat(Number(tag[1]))} ${children.trim()}\n`;
      if (tag === 'pre') {
        const code = node.querySelector?.('code');
        const language = code?.className?.match?.(/(?:^|\s)language-([\w+-]+)/)?.[1] || '';
        const value = (code?.textContent || node.textContent || '').replace(/\n+$/, '');
        return `\n\`\`\`${language}\n${value}\n\`\`\`\n`;
      }
      if (tag === 'table') {
        const rows = [...(node.querySelectorAll?.('tr') || [])].map(row =>
          [...(row.querySelectorAll?.('th, td') || [])].map(cell => (cell.innerText || cell.textContent || '').trim()));
        if (!rows.length) return '';
        const lines = rows.map(row => `| ${row.join(' | ')} |`);
        if (rows.length > 1) lines.splice(1, 0, `| ${rows[0].map(() => '---').join(' | ')} |`);
        return `\n${lines.join('\n')}\n`;
      }
      if (tag === 'li') return `\n${node.parentElement?.tagName?.toLowerCase() === 'ol' ? '1.' : '-'} ${children.trim()}`;
      if (['p', 'ul', 'ol', 'blockquote', 'div', 'section'].includes(tag)) return `\n${children.trim()}\n`;
      return children;
    };
    return roots.map(root => {
      const copy = root.cloneNode?.(true);
      if (!copy) return root.innerText || root.textContent || '';
      for (const selector of excluded) {
        for (const element of copy.querySelectorAll?.(selector) || []) element.remove?.();
      }
      return serialize(copy);
    }).join('\n').replace(/[\t ]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n').trim();
  };
  const completionSignal = () => [...document.querySelectorAll('[role="status"], [aria-live]')].some(node =>
    /Claude (?:has )?(?:finished (?:responding|the response)|terminou (?:a resposta|de responder))/i
      .test(node.innerText || node.textContent || ''));
  const messages = () => [...document.querySelectorAll(
    '[data-testid="user-message"], .font-claude-response, [data-testid="assistant-message"]'
  )].filter((node, _, all) => !all.some(parent => parent !== node && parent.contains(node)));
  globalThis.GovernancaPlatform = {claude, editor, composer, fileRoot, sendButton, stopButton, role, messages,
    responseText, completionSignal, streaming: () => [...document.querySelectorAll('button')].some(stopButton),
    ready: () => [...document.querySelectorAll('button')].some(sendButton)};
})();
