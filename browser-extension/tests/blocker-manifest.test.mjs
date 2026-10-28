import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('o pacote limita a injeção ao ChatGPT, ao Claude e à API local do Harness', async () => {
  const manifest = JSON.parse(await readFile(new URL('../manifest.json', import.meta.url)));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.host_permissions, ['https://chatgpt.com/*', 'https://claude.ai/*', 'http://127.0.0.1:18080/*']);
  assert.equal(manifest.version, '0.6.0');
  assert.deepEqual(manifest.permissions, ['storage', 'tabs', 'alarms']);
  assert.deepEqual(manifest.content_scripts.map(script => [script.world, script.run_at]), [
    ['MAIN', 'document_start'], ['MAIN', 'document_start'],
    ['ISOLATED', 'document_start'], ['ISOLATED', 'document_start']
  ]);
  assert.deepEqual(manifest.content_scripts[0].js, ['src/content/capture-adapter.js', 'src/content/blocker-main.js', 'src/content/network-probe-main.js']);
  assert.deepEqual(manifest.content_scripts[1].js, ['src/content/blocker-main.js', 'src/content/claude-network-probe-main.js']);
  assert.deepEqual(manifest.content_scripts[2].js, ['src/content/capture-adapter.js', 'src/content/platform.js', 'src/content/files.js', 'src/content/policy-engine.js',
    'src/content/policy-messages.js', 'src/content/observer.js', 'src/content/blocker-bridge.js', 'src/content/network-bridge.js']);
  assert.deepEqual(manifest.content_scripts[3].js, ['src/content/platform.js', 'src/content/files.js', 'src/content/policy-engine.js',
    'src/content/policy-messages.js', 'src/content/observer.js', 'src/content/blocker-bridge.js']);
  assert.deepEqual(manifest.content_scripts[0].matches, ['https://chatgpt.com/*']);
  assert.deepEqual(manifest.content_scripts[1].matches, ['https://claude.ai/*']);
  assert.deepEqual(manifest.content_scripts[2].matches, ['https://chatgpt.com/*']);
  assert.deepEqual(manifest.content_scripts[3].matches, ['https://claude.ai/*']);
  for (const path of [...manifest.content_scripts.flatMap(script => script.js), manifest.background.service_worker, manifest.action.default_popup]) {
    await readFile(new URL('../' + path, import.meta.url));
  }
  const worker = await readFile(new URL('../src/background/service-worker.js', import.meta.url), 'utf8');
  assert.match(worker, /!validConversationObservation\(item\.conversation, sender\.url\)/);
  await readFile(new URL('../src/background/capture-validation.js', import.meta.url));
  assert.match(worker, /'http:\/\/127\.0\.0\.1:18080'/);
  assert.match(worker, /import \{CONFIG\} from '\.\/config\.js'/);
  assert.match(worker, /X-Machine-Signature/);
  assert.match(worker, /device_installation_id: installationId/);
  const popup = await readFile(new URL('../src/popup/popup.html', import.meta.url), 'utf8');
  assert.match(popup, /Captura prompts e respostas do ChatGPT e do Claude/);
  assert.match(popup, /metadados observados registrados, sem leitura do conteúdo do arquivo/);
  assert.doesNotMatch(popup, /Não envia nem grava prompts ou respostas/);
});
