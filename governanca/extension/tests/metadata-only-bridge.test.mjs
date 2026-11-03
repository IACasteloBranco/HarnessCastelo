import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../src/content/network-bridge.js', import.meta.url), 'utf8');
const marker = 'governanca-ai-network-probe-v1';
const attemptId = 'a3cc6a9e-64be-44e4-a989-53dc971b5dd0';

test('envia somente metadados para stream_captures', async () => {
  const windowListeners = new Map();
  const sent = [];
  const window = {
    addEventListener: (type, callback) => windowListeners.set(type, callback),
    postMessage: data => windowListeners.get('message')?.({source: window, origin: 'https://chatgpt.com', data})
  };
  const chrome = {runtime: {
    onMessage: {addListener: callback => { chrome.listener = callback; }},
    sendMessage: async message => {
      sent.push(message);
      return message.type === 'probe_config' ? {ok: true, data: {enabled: true}} : {ok: true, data: {status: 'stored'}};
    }
  }};
  vm.runInNewContext(source, {window, chrome, location: {origin: 'https://chatgpt.com'}, Date, Map});
  chrome.listener({type: 'probe_config', enabled: true}, {}, () => {});

  windowListeners.get('message')({source: window, origin: 'https://chatgpt.com', data: {
    marker, transport: 'fetch', phase: 'stream_capture', attemptId,
    path: '/backend-api/f/conversation', captureStatus: 'complete', protocolDone: true,
    readerDone: false, readerAbortedAfterDone: true, truncated: false, status: 200,
    contentType: 'text/event-stream', requestId: 1, responseChars: 18, bytes: 42,
    chunks: 2, frames: 3, doneMarkers: 1, streamElapsedMs: 100,
    eventTypes: [], eventShapes: [], eventSequence: [],
    promptText: 'PROMPT-SYNTHETIC-DO-NOT-TRANSMIT', text: 'RESPONSE-SYNTHETIC-DO-NOT-TRANSMIT'
  }});

  const message = sent.find(item => item.type === 'stream_capture');
  assert.ok(message);
  assert.equal(message.payload.response_chars, 18);
  assert.equal(message.payload.adapter_version, '0.3.0');
  assert.equal(Object.hasOwn(message.payload, 'prompt_text'), false);
  assert.equal(Object.hasOwn(message.payload, 'response_text'), false);
  assert.doesNotMatch(JSON.stringify(message.payload), /PROMPT-SYNTHETIC|RESPONSE-SYNTHETIC/);
});

test('encaminha MIME e contexto de conversa sem propagar URL ou campos extras', async () => {
  const windowListeners = new Map();
  const sent = [];
  const window = {
    addEventListener: (type, callback) => windowListeners.set(type, callback),
    postMessage: data => windowListeners.get('message')?.({source: window, origin: 'https://chatgpt.com', data})
  };
  const chrome = {runtime: {
    onMessage: {addListener: callback => { chrome.listener = callback; }},
    sendMessage: async message => { sent.push(message); return {ok: true, data: {status: 'stored'}}; }
  }};
  vm.runInNewContext(source, {window, chrome, location: {origin: 'https://chatgpt.com'}, Date, Map});
  chrome.listener({type: 'probe_config', enabled: true}, {}, () => {});

  windowListeners.get('message')({source: window, origin: 'https://chatgpt.com', data: {
    marker, phase: 'artifact_metadata', payload: {
      artifact_id: 'b3cc6a9e-64be-44e4-a989-53dc971b5d11', platform: 'chatgpt_web', source: 'download_headers',
      file_name: 'synthetic.csv', mime_type: 'text/csv', size_bytes: null,
      conversation_context: {conversation_id: '11111111-1111-4111-8111-111111111111', source: 'active_route_at_request'},
      size_source: 'unavailable', observed_at: '2026-10-14T12:00:00Z',
      url: 'https://chatgpt.com/c/11111111-1111-4111-8111-111111111111?secret=synthetic', content: 'must not pass'
    }
  }});

  const message = sent.find(item => item.type === 'artifact_metadata');
  assert.ok(message);
  assert.equal(message.payload.mime_type, 'text/csv');
  assert.equal(message.payload.conversation_context.conversation_id, '11111111-1111-4111-8111-111111111111');
  assert.equal(message.payload.size_source, 'unavailable');
  assert.equal(Object.hasOwn(message.payload, 'url'), false);
  assert.equal(Object.hasOwn(message.payload, 'content'), false);
});
