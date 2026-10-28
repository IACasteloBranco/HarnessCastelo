import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../src/content/network-probe-main.js', import.meta.url), 'utf8');
const adapterSource = await readFile(new URL('../src/content/capture-adapter.js', import.meta.url), 'utf8');
const origin = 'https://chatgpt.com';
const marker = 'governanca-ai-network-probe-v1';

function makeProbe({abortAfterDone, finished = true, endTurn = finished, frames: fixtureFrames}) {
  const listeners = new Map();
  const posted = [];
  const frames = (fixtureFrames || [
    `data: ${JSON.stringify({type: 'message', message: {author: {role: 'assistant'},
      status: finished ? 'finished_successfully' : 'in_progress',
      end_turn: endTurn ? true : null,
      content: {parts: ['Resposta sintética']}}})}\n\n`,
    ...(abortAfterDone ? ['data: [DONE]\n\n'] : []),
  ]).map(value => new TextEncoder().encode(value));
  let readIndex = 0;
  const reader = {
    async read() {
      if (readIndex < frames.length) return {done: false, value: frames[readIndex++]};
      const error = new Error('Synthetic reader abort');
      error.name = 'AbortError';
      throw error;
    },
    async cancel() {},
  };
  const response = {
    ok: true,
    status: 200,
    headers: {get: name => name.toLowerCase() === 'content-type' ? 'text/event-stream' : null},
    body: {},
    clone: () => ({body: {getReader: () => reader}}),
  };
  const window = {
    fetch: async () => response,
    addEventListener: (type, callback) => listeners.set(type, callback),
    postMessage: (data, messageOrigin) => {
      posted.push(data);
      listeners.get('message')?.({source: window, origin: messageOrigin, data});
    },
  };
  let id = 0;
  const context = {
    window,
    document: {},
    location: {origin, href: `${origin}/g/test`},
    crypto: {randomUUID: () => `00000000-0000-4000-8000-${String(++id).padStart(12, '0')}`},
    performance: {now: () => 1},
    TextDecoder,
    URL,
  };
  vm.runInNewContext(adapterSource, context);
  vm.runInNewContext(source, context);
  window.postMessage({marker, phase: 'capture_config', enabled: true}, origin);
  return {window, posted};
}

async function captureFrom(probe) {
  await probe.window.fetch(`${origin}/backend-api/f/conversation`, {method: 'POST'});
  for (let attempt = 0; attempt < 20; attempt++) {
    const capture = probe.posted.find(item => item.phase === 'stream_capture');
    if (capture) return capture;
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  throw new Error('Timed out waiting for synthetic stream capture');
}

test('classifies AbortError after the terminal marker as complete and preserves the abort signal', async () => {
  const probe = makeProbe({abortAfterDone: true});
  const capture = await captureFrom(probe);
  assert.equal(capture.captureStatus, 'complete');
  assert.equal(capture.protocolDone, true);
  assert.equal(capture.readerDone, false);
  assert.equal(capture.readerAbortedAfterDone, true);
  assert.equal(capture.truncated, false);
  assert.equal(capture.responseChars, 'Resposta sintética'.length);
  assert.equal(capture.text, 'Resposta sintética');
  const errorEvent = probe.posted.find(item => item.phase === 'stream_error');
  assert.equal(errorEvent.errorKind, 'AbortError');
  assert.equal(errorEvent.readerAbortedAfterDone, true);
});

test('keeps an abort before the terminal marker incomplete', async () => {
  const probe = makeProbe({abortAfterDone: false});
  const capture = await captureFrom(probe);
  assert.equal(capture.captureStatus, 'incomplete');
  assert.equal(capture.protocolDone, false);
  assert.equal(capture.readerDone, false);
  assert.equal(capture.readerAbortedAfterDone, false);
  assert.equal(capture.responseChars, 'Resposta sintética'.length);
  assert.equal(capture.text, 'Resposta sintética');
});

test('reconstructs DPU snapshots and append patches in order', async () => {
  const frames = [
    `event: delta\ndata: ${JSON.stringify({p: '', o: 'add', v: {message: {author: {role: 'system'},
      status: 'finished_successfully', content: {parts: ['não incluir']}}}})}\n\n`,
    `event: delta\ndata: ${JSON.stringify({v: {message: {id: 'm1', author: {role: 'assistant'},
      status: 'in_progress', content: {parts: ['ABACA']}}}})}\n\n`,
    `event: delta\ndata: ${JSON.stringify({v: [{p: '/message/content/parts/0', o: 'append', v: 'TE 42 ✅'}], o: 'patch'})}\n\n`,
    `event: delta\ndata: ${JSON.stringify({v: [
      {p: '/message/status', o: 'replace', v: 'finished_successfully'},
      {p: '/message/end_turn', o: 'replace', v: true}
    ], o: 'patch'})}\n\n`,
    'data: [DONE]\n\n'
  ];
  const capture = await captureFrom(makeProbe({abortAfterDone: true, frames}));
  assert.equal(capture.text, 'ABACATE 42 ✅');
  assert.equal(capture.captureStatus, 'complete');
});

test('appends assistant text deltas after a partial DPU snapshot', async () => {
  const frames = [
    `event: delta\ndata: ${JSON.stringify({v: {message: {id: 'm1', author: {role: 'assistant'},
      status: 'in_progress', content: {parts: ['ACK-']}}}})}\n\n`,
    `event: delta\ndata: ${JSON.stringify({v: '10'})}\n\n`,
    'data: [DONE]\n\n'
  ];
  const capture = await captureFrom(makeProbe({abortAfterDone: true, frames}));
  assert.equal(capture.text, 'ACK-10');
  assert.equal(capture.captureStatus, 'complete');
});

test('the terminal marker completes a response without assistant status metadata', async () => {
  const capture = await captureFrom(makeProbe({abortAfterDone: true, finished: false}));
  assert.equal(capture.captureStatus, 'complete');
  assert.equal(capture.text, 'Resposta sintética');
});

test('the terminal marker completes a response without end_turn metadata', async () => {
  const capture = await captureFrom(makeProbe({abortAfterDone: true, endTurn: false}));
  assert.equal(capture.captureStatus, 'complete');
});

test('ignores tool calls, tool output and thoughts before the final assistant text', async () => {
  const frame = value => `event: delta\ndata: ${JSON.stringify(value)}\n\n`;
  const frames = [
    frame({v: {message: {id: 'code', author: {role: 'assistant'}, recipient: 'python',
      status: 'finished_successfully', end_turn: false,
      content: {content_type: 'code', parts: ['print(1 + 1)']}}}}),
    frame({v: {message: {id: 'thought', author: {role: 'assistant'}, recipient: 'all',
      status: 'finished_successfully', end_turn: false,
      content: {content_type: 'thoughts', parts: ['thinking']}}}}),
    frame({v: {message: {id: 'tool', author: {role: 'tool'}, recipient: 'all',
      content: {content_type: 'execution_output', parts: ['2']}}}}),
    frame({v: {message: {id: 'final', author: {role: 'assistant'}, recipient: 'all',
      status: 'in_progress', end_turn: null,
      content: {content_type: 'text', parts: ['Resposta 2']}}}}),
    frame({o: 'patch', v: [{p: '/message/status', o: 'replace', v: 'finished_successfully'},
      {p: '/message/end_turn', o: 'replace', v: true}]}),
    'data: [DONE]\n\n'
  ];
  const capture = await captureFrom(makeProbe({abortAfterDone: true, frames}));
  assert.equal(capture.text, 'Resposta 2');
  assert.equal(capture.captureStatus, 'complete');
});

test('keeps two overlapping POST streams paired with their own attempt IDs', async () => {
  const posted = [];
  const listeners = new Map();
  const attrs = new Map();
  const root = {getAttribute: key => attrs.get(key),
    setAttribute: (key, value) => attrs.set(key, value), removeAttribute: key => attrs.delete(key)};
  const response = (answer, delay) => {
    const frames = [
      `data: ${JSON.stringify({v: {message: {author: {role: 'assistant'},
        status: 'finished_successfully', end_turn: true, content: {parts: [answer]}}}})}\n\n`,
      'data: [DONE]\n\n'
    ].map(value => new TextEncoder().encode(value));
    let index = 0;
    return {ok: true, status: 200, headers: {get: () => 'text/event-stream'}, body: {},
      clone: () => ({body: {getReader: () => ({async read() {
        if (delay) await new Promise(resolve => setTimeout(resolve, delay));
        return index < frames.length ? {done: false, value: frames[index++]} : {done: true};
      }})}})};
  };
  const window = {fetch: async (_url, options) => response(options.answer, options.delay),
    addEventListener: (name, callback) => listeners.set(name, callback),
    postMessage: (data, messageOrigin) => {
      posted.push(data);
      listeners.get('message')?.({source: window, origin: messageOrigin, data});
    }};
  const context = {window, document: {documentElement: root},
    location: {origin, href: `${origin}/g/test`},
    crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000099'},
    performance: {now: () => 1}, TextDecoder, URL};
  vm.runInNewContext(adapterSource, context);
  vm.runInNewContext(source, context);
  window.postMessage({marker, phase: 'capture_config', enabled: true}, origin);
  const first = '00000000-0000-4000-8000-000000000001';
  const second = '00000000-0000-4000-8000-000000000002';
  attrs.set('data-governanca-probe-attempt', first);
  attrs.set('data-governanca-probe-until', String(Date.now() + 10000));
  const a = window.fetch(`${origin}/backend-api/f/conversation`, {method: 'POST', answer: 'primeira', delay: 5});
  attrs.set('data-governanca-probe-attempt', second);
  attrs.set('data-governanca-probe-until', String(Date.now() + 10000));
  const b = window.fetch(`${origin}/backend-api/f/conversation`, {method: 'POST', answer: 'segunda', delay: 0});
  await Promise.all([a, b]);
  for (let i = 0; i < 30 && posted.filter(item => item.phase === 'stream_capture').length < 2; i++)
    await new Promise(resolve => setTimeout(resolve, 5));
  const captures = posted.filter(item => item.phase === 'stream_capture');
  assert.equal(captures.length, 2);
  assert.deepEqual(Object.fromEntries(captures.map(item => [item.attemptId, item.text])),
    {[first]: 'primeira', [second]: 'segunda'});
  assert.equal(captures[0].attemptId, second);
});
