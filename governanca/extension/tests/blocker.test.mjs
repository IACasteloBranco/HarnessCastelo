import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const mainSource = await readFile(new URL('../src/content/blocker-main.js', import.meta.url), 'utf8');
const bridgeSource = await readFile(new URL('../src/content/blocker-bridge.js', import.meta.url), 'utf8');
const policySource = await readFile(new URL('../src/content/policy-engine.js', import.meta.url), 'utf8');
const messagesSource = await readFile(new URL('../src/content/policy-messages.js', import.meta.url), 'utf8');
const protocolVersion = 1;
function bridgeWindow(listeners, origin, attributes) {
  const window = {addEventListener: (type, listener) => listeners.set(type, listener), postMessage: message => {
    if (message.phase === 'ping') listeners.get('message')?.({source: window, origin,
      data: {marker: 'governanca-ai-prompt-block-v1', phase: 'pong', protocolVersion,
        blocked: attributes.get('data-governanca-block-prompts') !== 'allow'}});
  }};
  return window;
}

for (const [origin, endpoint] of [['https://chatgpt.com', '/backend-api/abc/conversation'],
  ['https://claude.ai', '/api/organizations/org/chat_conversations/chat/completion']]) {
test(`${origin}: bloqueio de rede exige permissão de uso único`, async () => {
  const calls = [];
  const messages = [];
  const listeners = new Map();
  const attrs = new Map([['data-governanca-block-prompts', 'block']]);
  const root = {getAttribute: key => attrs.get(key), setAttribute: (key, value) => attrs.set(key, value),
    removeAttribute: key => attrs.delete(key)};
  const window = {
    fetch: (...args) => { calls.push(args); return Promise.resolve({ok: true}); },
    postMessage: message => {
      messages.push(message);
      if (message.phase === 'backend_preflight') listeners.get('message')?.({source: window,
        origin, data: {marker: 'governanca-ai-prompt-block-v1', phase: 'backend_preflight_result',
          requestId: message.requestId, protocolVersion, available: true}});
    },
    addEventListener: (type, listener) => listeners.set(type, listener)
  };
  runInNewContext(mainSource, {window, document: {documentElement: root},
    location: {href: origin + '/', origin}, crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000001'},
    URL, Symbol, Proxy, Reflect, Promise, DOMException, setTimeout, clearTimeout});
  await assert.rejects(window.fetch(endpoint, {method: 'POST'}), {name: 'AbortError'});
  assert.equal(calls.length, 0);
  assert.equal(messages[0].phase, 'network_blocked');
  await window.fetch('/backend-api/conversation/abc', {method: 'POST'});
  await window.fetch(endpoint, {method: 'GET'});
  assert.equal(calls.length, 2);
  attrs.set('data-governanca-block-prompts', 'allow');
  attrs.set('data-governanca-allow-until', String(Date.now() + 15000));
  await window.fetch(endpoint, {method: 'POST'});
  assert.equal(calls.length, 3);
  assert.equal(attrs.get('data-governanca-block-prompts'), 'block');
  await assert.rejects(window.fetch(endpoint, {method: 'POST'}), {name: 'AbortError'});
  assert.equal(calls.length, 3);
});
}

test('backend indisponível retém o POST da conversa', async () => {
  const calls = [];
  const messages = [];
  const listeners = new Map();
  const origin = 'https://chatgpt.com';
  const attrs = new Map([['data-governanca-block-prompts', 'allow'],
    ['data-governanca-allow-until', String(Date.now() + 15000)]]);
  const root = {getAttribute: key => attrs.get(key), setAttribute: (key, value) => attrs.set(key, value),
    removeAttribute: key => attrs.delete(key)};
  const window = {
    fetch: (...args) => { calls.push(args); return Promise.resolve({ok: true}); },
    postMessage: message => {
      messages.push(message);
      if (message.phase === 'backend_preflight') listeners.get('message')?.({source: window,
        origin, data: {marker: 'governanca-ai-prompt-block-v1', phase: 'backend_preflight_result',
          requestId: message.requestId, protocolVersion, available: false, reason: 'backend_unavailable'}});
    },
    addEventListener: (type, listener) => listeners.set(type, listener)
  };
  runInNewContext(mainSource, {window, document: {documentElement: root},
    location: {href: origin + '/', origin}, crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000002'},
    URL, Symbol, Proxy, Reflect, Promise, DOMException, setTimeout, clearTimeout});

  await assert.rejects(window.fetch('/backend-api/conversation', {method: 'POST'}), {name: 'AbortError'});
  assert.equal(calls.length, 0);
  assert.equal(attrs.get('data-governanca-block-prompts'), 'block');
  assert.equal(messages.some(message => message.phase === 'network_blocked' &&
    message.reason === 'backend_unavailable'), true);
});

test('versão incompatível do bridge retém o POST e informa o motivo', async () => {
  const calls = [];
  const messages = [];
  const listeners = new Map();
  const origin = 'https://chatgpt.com';
  const attrs = new Map([['data-governanca-block-prompts', 'allow'],
    ['data-governanca-allow-until', String(Date.now() + 15000)]]);
  const root = {getAttribute: key => attrs.get(key), setAttribute: (key, value) => attrs.set(key, value),
    removeAttribute: key => attrs.delete(key)};
  const window = {
    fetch: (...args) => { calls.push(args); return Promise.resolve({ok: true}); },
    postMessage: message => {
      messages.push(message);
      if (message.phase === 'backend_preflight') listeners.get('message')?.({source: window,
        origin, data: {marker: 'governanca-ai-prompt-block-v1', phase: 'backend_preflight_result',
          requestId: message.requestId, available: true}});
    },
    addEventListener: (type, listener) => listeners.set(type, listener)
  };
  runInNewContext(mainSource, {window, document: {documentElement: root},
    location: {href: origin + '/', origin}, crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000003'},
    URL, Symbol, Proxy, Reflect, Promise, DOMException, setTimeout, clearTimeout});

  await assert.rejects(window.fetch('/backend-api/conversation', {method: 'POST'}), {name: 'AbortError'});
  assert.equal(calls.length, 0);
  assert.equal(messages.some(message => message.phase === 'network_blocked' &&
    message.reason === 'extension_mismatch'), true);
});

test('Enter, clique e submit ficam bloqueados quando a inspeção não responde', async () => {
  let captures = 0;
  const listeners = new Map();
  const toasts = [];
  const attributes = new Map();
  const form = {contains: () => true};
  const field = {innerText: 'Como calcular DAS?', contains: () => true, closest: () => form};
  const root = {setAttribute: (key, value) => attributes.set(key, value),
    getAttribute: key => attributes.get(key), removeAttribute: key => attributes.delete(key), append: () => {}};
  const document = {
    documentElement: root, body: {append: () => {}},
    addEventListener: () => {},
    querySelector: selector => selector === '#prompt-textarea' ? field : null,
    createElement: () => {
      const toast = {setAttribute: () => {}, style: {}, remove: () => {}};
      toasts.push(toast);
      return toast;
    }
  };
  const window = bridgeWindow(listeners, 'https://chatgpt.com', attributes);
  const port = {onMessage: {addListener: () => {}}, onDisconnect: {addListener: () => {}}, postMessage: () => {}};
  const chrome = {runtime: {connect: () => port,
    sendMessage: message => message.type === 'inspect_sensitive_text'
      ? Promise.reject(new Error('inspection unavailable')) : Promise.resolve()}};
  const projectId = 'g-p-6abe9293e8248191ada3632b6a5316a6';
  const pageLocation = {origin: 'https://chatgpt.com', href: `https://chatgpt.com/g/${projectId}-eduardo/c/conversa`};
  runInNewContext(`${policySource}\n${messagesSource}\n${bridgeSource}`, {window, document, chrome,
    location: pageLocation, URL, Date, setTimeout: () => {}, globalThis: {
      GovernancaPlatform: {fileRoot: () => form},
      GovernancaFiles: {
        rememberSelection: input => fileSelections.push(input),
        observe: () => ({capture_status: 'unavailable', items: [], truncated: false})
      },
      GovernancaCaptureAttempt: () => { captures++; }
    }});
  const event = extra => ({...extra, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; },
    stopImmediatePropagation() { this.stopped = true; }});
  const enter = event({key: 'Enter', shiftKey: false, isComposing: false, target: field});
  listeners.get('keydown')(enter);
  assert.equal(enter.prevented, true);
  assert.equal(enter.stopped, true);
  const button = {matches: () => true};
  const click = event({target: {closest: () => button}});
  listeners.get('click')(click);
  assert.equal(click.prevented, true);
  const submit = event({target: form});
  listeners.get('submit')(submit);
  assert.equal(submit.prevented, true);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.match(toasts.at(-1).textContent, /inspeção indisponível/i);
  assert.equal(attributes.get('data-governanca-block-prompts'), 'block');
});

test('clique e Enter enviam a prévia mascarada somente após confirmação', async () => {
  const listeners = new Map();
  const attributes = new Map();
  const previews = [];
  const dialogs = [];
  const field = {textContent: 'CPF 123.456.789-09', contains: target => target === field,
    closest: () => form, focus() {}, dispatchEvent() {}, get innerText() { return this.textContent; }};
  const form = {contains: () => true, querySelectorAll: () => [button]};
  const event = target => ({target, preventDefault() { this.prevented = true; }, stopImmediatePropagation() {}});
  const button = {type: 'submit', isConnected: true, getAttribute: name => name === 'aria-label' ? 'Enviar' : null,
    matches: selector => selector === 'button', click: () => {
      listeners.get('click')(event({closest: () => button}));
      listeners.get('submit')?.(event(form));
    }};
  const root = {setAttribute: (key, value) => attributes.set(key, value),
    getAttribute: key => attributes.get(key), removeAttribute: key => attributes.delete(key)};
  const makeNode = tag => ({tag, children: [], style: {}, addEventListener(type, listener) { this[type] = listener; },
    append(...children) { this.children.push(...children); }, setAttribute() {}, remove() {}, close() {},
    showModal() { previews.push(this.children[2].textContent); setTimeout(() => this.children[3].children[1].click(), 0); },
    click() { this.click?.(); }});
  const document = {documentElement: root, body: {append() {}}, addEventListener() {},
    querySelector: selector => selector === '#prompt-textarea' ? field : null, querySelectorAll: () => [],
    createElement: tag => {
      const node = makeNode(tag);
      if (tag === 'dialog') dialogs.push(node);
      if (tag === 'button') node.click = () => node.clickListener?.();
      node.addEventListener = (type, listener) => { node[`${type}Listener`] = listener; };
      return node;
    }};
  const port = {onMessage: {addListener: listener => { listeners.set('policy', listener); }},
    onDisconnect: {addListener() {}}, postMessage() {}};
  const window = bridgeWindow(listeners, 'https://chatgpt.com', attributes);
  let captures = 0;
  const chrome = {runtime: {connect: () => port, sendMessage: message => message.type === 'inspect_sensitive_text'
    ? Promise.resolve({ok: true, data: {action: 'mask', text: 'CPF [CPF_1]', requires_confirmation: true,
      categories: ['CPF'], policy_version: 'governanca-1'}}) : Promise.resolve({})}};
  const platform = {fileRoot: () => form, composer: () => form, sendButton: node => node === button};
  runInNewContext(`${policySource}\n${messagesSource}\n${bridgeSource}`, {window, document, chrome,
    location: {origin: 'https://chatgpt.com', href: 'https://chatgpt.com/c/synthetic'}, URL, Date, InputEvent: class {},
    setTimeout, globalThis: {GovernancaPlatform: platform,
      GovernancaFiles: {observe: () => ({capture_status: 'unavailable', items: [], truncated: false})},
      GovernancaCaptureAttempt: () => { captures++; }}});
  listeners.get('policy')({type: 'block_policy', blocked: false, machineAssigned: true,
    protocolVersion, protocolCompatible: true});
  listeners.get('message')({source: window, origin: 'https://chatgpt.com', data: {
    marker: 'governanca-ai-prompt-block-v1', phase: 'pong', protocolVersion, blocked: true
  }});
  const click = event({closest: () => button});
  listeners.get('click')(click);
  assert.equal(click.prevented, true);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.deepEqual(previews, ['CPF [CPF_1]']);
  assert.equal(dialogs[0].className, 'governanca-mask-dialog');
  assert.match(dialogs[0].style.cssText, /#102f4a/);
  assert.equal(dialogs[0].children[3].children[1].className, 'governanca-mask-confirm');
  assert.equal(field.textContent, 'CPF [CPF_1]');
  assert.equal(captures, 1);
  assert.equal(attributes.get('data-governanca-block-prompts'), 'allow');
  await new Promise(resolve => setTimeout(resolve, 510));
  field.textContent = 'CPF 123.456.789-09';
  const enter = {key: 'Enter', shiftKey: false, isComposing: false, target: field,
    preventDefault() { this.prevented = true; }, stopImmediatePropagation() {}};
  listeners.get('keydown')(enter);
  assert.equal(enter.prevented, true);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(captures, 2);
  assert.equal(field.textContent, 'CPF [CPF_1]');
  assert.deepEqual(previews, ['CPF [CPF_1]', 'CPF [CPF_1]']);
});

test('anexo visível recebe tempo para upload e mantém a barreira de uso único', () => {
  const listeners = new Map();
  const attrs = new Map();
  const root = {setAttribute: (key, value) => attrs.set(key, value),
    getAttribute: key => attrs.get(key), removeAttribute: key => attrs.delete(key)};
  const form = {contains: () => true};
  const editor = {innerText: '', contains: () => true, closest: () => form};
  const document = {documentElement: root, addEventListener: () => {},
    querySelector: selector => selector === '#prompt-textarea' ? editor : null};
  const window = bridgeWindow(listeners, 'https://claude.ai', attrs);
  let policy;
  const port = {onMessage: {addListener: callback => { policy = callback; }},
    onDisconnect: {addListener: () => {}}, postMessage: () => {}};
  const chrome = {runtime: {connect: () => port, sendMessage: async () => ({})}};
  const now = Date.now();
  let captured;
  runInNewContext(`${policySource}\n${messagesSource}\n${bridgeSource}`,
    {window, document, chrome, location: {origin: 'https://claude.ai', href: 'https://claude.ai/new'},
      URL, Date, setTimeout: () => {}, globalThis: {
        GovernancaFiles: {observe: () => ({capture_status: 'observed', items: [{capture_status: 'presence_only'}]})},
        GovernancaCaptureAttempt: value => { captured = value; }
      }});
  policy({type: 'block_policy', blocked: false, machineAssigned: true, protocolVersion, protocolCompatible: true});
  listeners.get('keydown')({key: 'Enter', shiftKey: false, isComposing: false, target: editor});
  const expiry = Number(attrs.get('data-governanca-allow-until'));
  assert.ok(expiry >= now + 119000 && expiry <= now + 121000);
  assert.equal(attrs.get('data-governanca-block-prompts'), 'allow');
  assert.equal(captured.capture_status, 'observed');
});

test('network-blocked attempt rechecks composer text without capturing or allowing', () => {
  const listeners = new Map();
  const attributes = new Map();
  const messages = [];
  const notices = [];
  let captureCount = 0;
  let syncPolicy;
  const form = {contains: () => true};
  const field = {innerText: '', contains: () => true, closest: () => form};
  const root = {setAttribute: (key, value) => attributes.set(key, value),
    getAttribute: key => attributes.get(key), removeAttribute: key => attributes.delete(key), append: () => {}};
  const document = {documentElement: root, body: {append: node => notices.push(node)}, addEventListener: () => {},
    querySelector: selector => selector === '#prompt-textarea' ? field : null,
    createElement: () => ({setAttribute: () => {}, style: {}, remove: () => {}, textContent: ''})};
  const window = bridgeWindow(listeners, 'https://chatgpt.com', attributes);
  const port = {onMessage: {addListener: callback => {syncPolicy = callback;}},
    onDisconnect: {addListener: () => {}}, postMessage: () => {}};
  runInNewContext(`${policySource}\n${messagesSource}\n${bridgeSource}`, {
    window, document, chrome: {runtime: {connect: () => port, sendMessage: message => {
      messages.push(message);
      return Promise.resolve({});
    }}}, location: {origin: 'https://chatgpt.com', href: 'https://chatgpt.com/c/synthetic'},
    URL, Date, setTimeout: () => {}, globalThis: {
      GovernancaFiles: {observe: () => ({capture_status: 'unavailable', items: [], truncated: false})},
      GovernancaCaptureAttempt: () => {captureCount++;}
    }
  });
  syncPolicy({type: 'block_policy', blocked: false, machineAssigned: true, protocolVersion, protocolCompatible: true});

  field.innerText = '-----BEGIN PRIVATE KEY-----';
  listeners.get('message')({source: window, origin: 'https://chatgpt.com', data: {
    marker: 'governanca-ai-prompt-block-v1', phase: 'network_blocked', reason: 'missing'
  }});
  assert.equal(messages.find(message => message.type === 'prompt_decision').method, 'network');
  assert.equal(messages.find(message => message.type === 'prompt_decision').action, 'BLOCK');
  assert.equal(messages.find(message => message.type === 'prompt_decision').findings[0].rule, 'R01');
  assert.match(notices.at(-1).textContent, /chave privada/i);
  assert.equal(captureCount, 0);
  assert.equal(attributes.get('data-governanca-block-prompts'), 'block');

  field.innerText = 'Pergunta sintética permitida';
  listeners.get('message')({source: window, origin: 'https://chatgpt.com', data: {
    marker: 'governanca-ai-prompt-block-v1', phase: 'network_blocked', reason: 'missing'
  }});
  assert.equal(messages.filter(message => message.type === 'prompt_decision').at(-1).action, 'ALLOW');
  assert.match(notices.at(-1).textContent, /continua no compositor; revise e use Enviar/i);
  assert.equal(captureCount, 0);
  assert.equal(attributes.get('data-governanca-block-prompts'), 'block');
});

test('allows an attachment-only prompt and passes the current composer snapshot', () => {
  const listeners = new Map();
  const attrs = new Map();
  const root = {setAttribute: (key, value) => attrs.set(key, value),
    getAttribute: key => attrs.get(key), removeAttribute: key => attrs.delete(key)};
  const form = {contains: () => true};
  const editor = {innerText: '', contains: () => true, closest: () => form};
  const document = {documentElement: root, addEventListener: () => {},
    querySelector: selector => selector === '#prompt-textarea' ? editor : null};
  const window = bridgeWindow(listeners, 'https://chatgpt.com', attrs);
  let policy;
  const port = {onMessage: {addListener: callback => { policy = callback; }},
    onDisconnect: {addListener: () => {}}, postMessage: () => {}};
  const observation = {capture_status: 'observed', items: [{name: 'sintetico.txt',
    mime_type: 'text/plain', size_bytes: 4, capture_status: 'metadata_only', source: 'selection_event'}], truncated: false};
  let captured;
  runInNewContext(`${policySource}\n${messagesSource}\n${bridgeSource}`,
    {window, document, chrome: {runtime: {connect: () => port, sendMessage: async () => ({})}},
      location: {origin: 'https://chatgpt.com', href: 'https://chatgpt.com/'}, URL, Date,
      setTimeout: () => {}, globalThis: {GovernancaFiles: {observe: composer => {
        assert.equal(composer, form);
        return observation;
      }}, GovernancaCaptureAttempt: value => { captured = value; }}});
  policy({type: 'block_policy', blocked: false, machineAssigned: true, protocolVersion, protocolCompatible: true});
  const submit = {target: editor, key: 'Enter', shiftKey: false, isComposing: false,
    preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; }};

  listeners.get('keydown')(submit);

  assert.equal(submit.prevented, undefined);
  assert.equal(captured, observation);
  assert.equal(attrs.get('data-governanca-block-prompts'), 'allow');
});
