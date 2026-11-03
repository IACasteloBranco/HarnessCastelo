import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../src/content/claude-network-probe-main.js', import.meta.url), 'utf8');
const marker = 'governanca-ai-claude-network-v1';
const attemptId = '00000000-0000-4000-8000-000000000001';
function varint(value) {
  const output = [];
  while (value > 127) {
    output.push((value & 127) | 128);
    value = Math.floor(value / 128);
  }
  output.push(value);
  return Uint8Array.from(output);
}

function message(number, payload) {
  return Uint8Array.from([...varint(number * 8 + 2), ...varint(payload.length), ...payload]);
}

function assistantFrame(text, role = 2) {
  const roleMessage = message(3, Uint8Array.from([...varint(3 * 8), ...varint(role)]));
  const textMessage = message(5, message(9, new TextEncoder().encode(text)));
  const payload = message(1, message(1, Uint8Array.from([...roleMessage, ...textMessage])));
  const header = new Uint8Array(5);
  new DataView(header.buffer).setUint32(1, payload.length);
  return Uint8Array.from([...header, ...payload]);
}

function makeProbe({frames, enabled = true, activeAttempt = true}) {
  const listeners = new Map();
  const posted = [];
  const response = {status: 200, body: {}, headers: {get: name => name === 'content-type' ? 'application/connect+proto' : null}};
  const chunks = frames.map(frame => [frame.slice(0, 3), frame.slice(3, 8), frame.slice(8)]).flat();
  let index = 0;
  response.clone = () => ({body: {getReader: () => ({
    async read() { return index < chunks.length ? {done: false, value: chunks[index++]} : {done: true}; },
    async cancel() {}
  })}});
  const window = {
    fetch: async () => response,
    addEventListener: (name, callback) => listeners.set(name, callback),
    postMessage: (data, origin) => {
      posted.push(data);
      listeners.get('message')?.({source: window, origin, data});
    }
  };
  const root = new Map(activeAttempt ? [
    ['data-governanca-probe-attempt', attemptId], ['data-governanca-probe-until', String(Date.now() + 60_000)]
  ] : []);
  vm.runInNewContext(source, {window, document: {documentElement: {getAttribute: key => root.get(key)}},
    location: {origin: 'https://claude.ai', href: 'https://claude.ai/chat/synthetic'},
    Date, DataView, TextDecoder, URL, Uint8Array, Symbol, Promise, setTimeout, clearTimeout});
  window.postMessage({marker, phase: 'capture_config', enabled}, 'https://claude.ai');
  return {window, posted, response};
}

async function waitForCapture(probe) {
  for (let i = 0; i < 20; i++) {
    const event = probe.posted.find(item => item.phase === 'assistant_text');
    if (event) return event;
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  return null;
}

test('reads split Connect frames from a clone and emits only assistant text', async () => {
  const probe = makeProbe({frames: [assistantFrame('texto de usuário', 1), assistantFrame('sinal')]});
  const original = await probe.window.fetch('/claudeai-rpc/anthropic.bard.api.v1alpha.ConversationService/StreamTimeline',
    {method: 'POST'});
  const capture = await waitForCapture(probe);
  assert.equal(original, probe.response);
  assert.deepEqual(JSON.parse(JSON.stringify(capture)), {marker, phase: 'assistant_text', attemptId, text: 'sinal'});
});

test('does not inspect when capture is disabled or no attempt is active', async () => {
  for (const options of [{enabled: false}, {activeAttempt: false}]) {
    const probe = makeProbe({...options, frames: [assistantFrame('sinal')]});
    await probe.window.fetch('/claudeai-rpc/anthropic.bard.api.v1alpha.ConversationService/StreamTimeline',
      {method: 'POST'});
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(probe.posted.some(item => item.phase === 'assistant_text'), false);
  }
});
