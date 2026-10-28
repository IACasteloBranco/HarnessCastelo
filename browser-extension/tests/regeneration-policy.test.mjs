import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const files = ['policy-engine.js', 'policy-messages.js', 'blocker-bridge.js'];
const source = (await Promise.all(files.map(name => readFile(new URL(`../src/content/${name}`, import.meta.url), 'utf8')))).join('\n');
const protocolVersion = 1;

test('re-evaluates policy and resumes the menu click only after restoring the interaction', async () => {
  const listeners = new Map();
  const attrs = new Map();
  const decisions = [];
  const regenerated = [];
  let replayed = 0;
  let policy;
  let userText = 'Prompt sintético seguro';
  const user = {get innerText() { return userText; }};
  const turnKey = '00000000-0000-4000-8000-000000000020';
  const turn = {querySelector: () => user, getAttribute: () => turnKey};
  const opener = {getAttribute: name => name === 'aria-label' ? 'Gerar resposta novamente' : null,
    closest: selector => selector === '[data-turn-key]' ? turn : null};
  const event = target => ({target, prevented: false, preventDefault() {this.prevented = true;},
    stopImmediatePropagation() {}});
  const menuItem = {isConnected: true, getAttribute: name => name === 'role' ? 'menuitem' : null,
    textContent: 'Tentar novamente • 6 Instant', closest(selector) {
      return selector === '[role="menuitem"]' ? this : null;
    }, click() {
      replayed++;
      const replay = event(menuItem);
      listeners.get('click')(replay);
      assert.equal(replay.prevented, false);
    }};
  const root = {setAttribute: (key, value) => attrs.set(key, value),
    removeAttribute: key => attrs.delete(key), getAttribute: key => attrs.get(key), append: () => {}};
  const document = {documentElement: root, body: root, addEventListener: () => {},
    querySelectorAll: () => [], querySelector: () => null,
    createElement: () => ({setAttribute: () => {}, style: {}, remove: () => {}})};
  const window = {addEventListener: (type, callback) => listeners.set(type, callback), postMessage: message => {
    if (message.phase === 'ping') listeners.get('message')?.({source: window, origin: 'https://chatgpt.com',
      data: {marker: 'governanca-ai-prompt-block-v1', phase: 'pong', protocolVersion, blocked: true}});
  }};
  const port = {onMessage: {addListener: callback => { policy = callback; }},
    onDisconnect: {addListener: () => {}}, postMessage: () => {}};
  const chrome = {runtime: {connect: () => port, sendMessage: async message => {decisions.push(message);}}};
  const context = {window, document, chrome, location: {origin: 'https://chatgpt.com'}, URL,
    Date, setTimeout: () => {}, globalThis: {GovernancaCaptureRegeneration: (text, key) => {
      regenerated.push([text, key]); return Promise.resolve(true);
    }}};
  vm.runInNewContext(source, context);
  policy({type: 'block_policy', blocked: false, machineAssigned: true, protocolVersion, protocolCompatible: true});
  const open = () => listeners.get('click')(event({closest: selector => selector === 'button' ? opener : null}));
  const select = () => {
    const click = event({closest: selector => selector === '[role="menuitem"]' ? menuItem : null});
    listeners.get('click')(click);
    return click;
  };

  open();
  assert.equal(attrs.get('data-governanca-block-prompts'), 'block');
  assert.equal(select().prevented, true);
  await new Promise(resolve => globalThis.setTimeout(resolve, 5));
  assert.deepEqual(regenerated, [['Prompt sintético seguro', turnKey]]);
  assert.equal(replayed, 1);
  assert.equal(attrs.get('data-governanca-block-prompts'), 'allow');
  assert.equal(decisions.at(-1).method, 'regenerate');

  assert.equal(select().prevented, true);
  assert.equal(replayed, 1);
  userText = '-----BEGIN PRIVATE KEY-----';
  open();
  assert.equal(select().prevented, true);
  assert.equal(regenerated.length, 1);
  assert.equal(attrs.get('data-governanca-block-prompts'), 'block');
});
