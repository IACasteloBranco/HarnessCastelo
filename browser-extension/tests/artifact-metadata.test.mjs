import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto} from 'node:crypto';
import {test} from 'node:test';
import vm from 'node:vm';

const probeSource = await readFile(new URL('../src/content/network-probe-main.js', import.meta.url), 'utf8');
const adapterSource = await readFile(new URL('../src/content/capture-adapter.js', import.meta.url), 'utf8');
const marker = 'governanca-ai-network-probe-v1';

function makeProbe(fetchImpl) {
  const listeners = new Map();
  const events = [];
  const location = {href: 'https://chatgpt.com/c/11111111-1111-4111-8111-111111111111', origin: 'https://chatgpt.com'};
  const window = {
    fetch: fetchImpl,
    addEventListener: (type, listener) => listeners.set(type, listener),
    postMessage: data => events.push(JSON.parse(JSON.stringify(data)))
  };
  const context = {
    window,
    location,
    URL,
    crypto: webcrypto,
    TextDecoder,
    performance
  };
  vm.runInNewContext(adapterSource, context);
  vm.runInNewContext(probeSource, context);
  return {
    window,
    events,
    navigate(href) { location.href = href; },
    enable() {
      listeners.get('message')({source: window, origin: 'https://chatgpt.com', data: {
        marker, phase: 'capture_config', enabled: true
      }});
    }
  };
}

async function settle() {
  await new Promise(resolve => setTimeout(resolve, 0));
}

test('does not inspect JSON response bodies for artifact metadata', async () => {
  let bodyReads = 0;
  const response = {
    ok: true,
    headers: new Headers({'Content-Type': 'application/json'}),
    get body() { bodyReads++; throw new Error('body must not be read'); },
    clone() { bodyReads++; throw new Error('response must not be cloned'); }
  };
  const probe = makeProbe(async () => response);
  probe.enable();

  await probe.window.fetch('https://chatgpt.com/backend-api/conversation/synthetic-id/interpreter/download');
  await settle();

  assert.equal(bodyReads, 0);
  assert.equal(probe.events.some(event => event.phase === 'artifact_metadata'), false);
});

test('captures transfer headers only and never reads the artifact body', async () => {
  const response = new Response('CONTEUDO-SINTETICO-DO-ARQUIVO', {headers: {
    'Content-Type': 'text/csv; charset=utf-8',
    'Content-Disposition': 'attachment; filename="teste.csv"',
    'Content-Length': '42'
  }});
  const probe = makeProbe(async () => response);
  probe.enable();

  await probe.window.fetch('https://chatgpt.com/backend-api/estuary/content?secret=not-forwarded');
  await settle();

  const item = probe.events.find(event => event.phase === 'artifact_metadata')?.payload;
  assert.ok(item);
  assert.equal(item.source, 'download_headers');
  assert.equal(item.file_name, 'teste.csv');
  assert.equal(item.mime_type, 'text/csv');
  assert.equal(item.size_bytes, 42);
  assert.deepEqual(JSON.parse(JSON.stringify(item.conversation_context)), {
    conversation_id: '11111111-1111-4111-8111-111111111111', source: 'active_route_at_request'
  });
  assert.equal(item.size_source, 'content_length');
  assert.equal(response.bodyUsed, false);
  assert.equal(JSON.stringify(item).includes('CONTEUDO-SINTETICO'), false);
  assert.equal(JSON.stringify(item).includes('secret'), false);
});

test('captures only response headers for recognized artifact downloads', async () => {
  let bodyReads = 0;
  const response = {
    ok: true,
    headers: new Headers({
      'Content-Type': 'application/pdf; charset=binary',
      'Content-Disposition': 'attachment; filename="relatorio.pdf"'
    }),
    get body() { bodyReads++; throw new Error('body must not be read'); },
    clone() { bodyReads++; throw new Error('response must not be cloned'); }
  };
  const probe = makeProbe(async () => response);
  probe.enable();

  await probe.window.fetch('https://chatgpt.com/backend-api/estuary/content');
  await settle();

  const item = probe.events.find(event => event.phase === 'artifact_metadata')?.payload;
  assert.deepEqual(JSON.parse(JSON.stringify(item)), {
    artifact_id: item.artifact_id, platform: 'chatgpt_web', source: 'download_headers',
    file_name: 'relatorio.pdf', mime_type: 'application/pdf', size_bytes: null,
    conversation_context: {conversation_id: '11111111-1111-4111-8111-111111111111', source: 'active_route_at_request'},
    size_source: 'unavailable',
    observed_at: item.observed_at
  });
  assert.equal(bodyReads, 0);
});

test('freezes only the conversation UUID at request start, without query or fragment', async () => {
  let finish;
  const probe = makeProbe(() => new Promise(resolve => { finish = resolve; }));
  probe.enable();
  const pending = probe.window.fetch('/backend-api/estuary/content?token=synthetic-secret');
  probe.navigate('https://chatgpt.com/g/g-synthetic/c/22222222-2222-4222-8222-222222222222');
  finish(new Response('', {status: 200, headers: {'Content-Type': 'application/pdf'}}));
  await pending;
  await settle();
  const item = probe.events.find(event => event.phase === 'artifact_metadata')?.payload;
  assert.equal(item.conversation_context.conversation_id, '11111111-1111-4111-8111-111111111111');
  assert.equal(JSON.stringify(item).includes('synthetic-secret'), false);
  assert.equal(JSON.stringify(item).includes('chatgpt.com'), false);
});

test('does not treat partial or encoded Content-Length as file size', async () => {
  for (const response of [
    new Response('', {status: 206, headers: {'Content-Type': 'text/csv', 'Content-Length': '42', 'Content-Range': 'bytes 0-41/100'}}),
    new Response('', {status: 200, headers: {'Content-Type': 'text/csv', 'Content-Length': '42', 'Content-Encoding': 'gzip'}})
  ]) {
    const probe = makeProbe(async () => response);
    probe.enable();
    await probe.window.fetch('/backend-api/estuary/content');
    await settle();
    const item = probe.events.find(event => event.phase === 'artifact_metadata')?.payload;
    assert.equal(item.size_bytes, null);
    assert.equal(item.size_source, 'unavailable');
    assert.equal(response.bodyUsed, false);
  }
});
