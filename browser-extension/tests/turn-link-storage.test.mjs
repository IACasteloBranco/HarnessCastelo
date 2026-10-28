import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
import vm from 'node:vm';
import {validConversationObservation} from '../src/background/capture-validation.js';

const source = (await readFile(new URL('../src/background/service-worker.js', import.meta.url), 'utf8'))
  .replace("import {CONFIG} from './config.js';", "const CONFIG = {mode: 'local', apiUrl: '', googleClientId: ''};")
  .replace("import {validConversationObservation} from './capture-validation.js';",
    'const validConversationObservation = globalThis.validConversationObservation;');
const turnKey = '00000000-0000-4000-8000-000000000020';
const interactionId = '00000000-0000-4000-8000-000000000099';
const promptHash = 'a'.repeat(64);

function captureReadyData() {
  return {installationId: '00000000-0000-4000-8000-000000000098', enabled: true,
    privacyAcceptance: {version: '2026-10-28.2', subject: 'SYN-1', accepted_at: new Date().toISOString()},
    authSession: {access_token: 'synthetic-access-token', employee_code: 'SYN-1',
      expires_at: Math.floor(Date.now() / 1000) + 3600},
    machineAssignment: {person_name: 'Pessoa Sintética', employee_id: 'SYN-1',
      department_code: 'TEST', key_matches: true}};
}

function worker({localData = {}, fetchImpl = async () => {throw new Error('unexpected fetch');}} = {}) {
  const local = {...localData};
  let onMessage;
  const storage = {
    async get(keys) {
      if (typeof keys === 'string') return {[keys]: local[keys]};
      return Object.fromEntries((Array.isArray(keys) ? keys : Object.keys(local)).map(key => [key, local[key]]));
    },
    async set(values) { Object.assign(local, values); },
    async remove(keys) { for (const key of keys) delete local[key]; },
    async setAccessLevel() {}
  };
  const chrome = {storage: {local: storage, session: storage},
    runtime: {getURL: path => `chrome-extension://test/${path}`,
      onMessage: {addListener: listener => {onMessage = listener;}},
      onConnect: {addListener: () => {}}}, alarms: {create: async () => {}, onAlarm: {addListener: () => {}}}};
  vm.runInNewContext(source, {chrome, crypto: webcrypto, URL, TextEncoder, Uint8Array,
    AbortSignal, btoa, fetch: fetchImpl, validConversationObservation, console});
  const sender = {tab: {id: 1}, frameId: 0,
    url: 'https://chatgpt.com/g/g-p-test/c/00000000-0000-4000-8000-000000000030'};
  const send = (message, source = sender) => new Promise(resolve => onMessage(message, source, resolve));
  return {send, local};
}

test('persists bounded turn-to-interaction links and rejects foreign routes', async () => {
  const {send, local} = worker({localData: captureReadyData()});
  const link = {conversationUrl: 'https://chatgpt.com/g/g-p-test/c/00000000-0000-4000-8000-000000000030',
    turnKey, interactionId, promptHash};
  const stored = await send({type: 'remember_turn', ...link});
  assert.equal(stored.ok, true);
  assert.equal(stored.data.stored, true);
  const found = await send({type: 'lookup_turn', conversationUrl: link.conversationUrl, turnKey});
  assert.equal(found.data.interaction_id, interactionId);
  assert.equal(found.data.prompt_hash, promptHash);
  assert.equal(local.turnLinks.length, 1);
  assert.equal((await send({type: 'remember_turn', ...link, conversationUrl: 'https://evil.example/c/turn'})).ok, false);

  await Promise.all(Array.from({length: 505}, (_, index) => send({type: 'remember_turn', ...link,
    turnKey: `00000000-0000-4000-8000-${String(index + 30).padStart(12, '0')}`})));
  assert.equal(local.turnLinks.length, 500);
});

test('reports a paused capture without storing prompt text', async () => {
  const {send, local} = worker({localData: captureReadyData()});
  local.enabled = false;
  const result = await send({type: 'capture_prompt', payload: {prompt: {text: 'SYNTHETIC-PRIVATE-MARKER'}}});

  assert.equal(result.ok, false);
  assert.equal(local.captureDiagnostics.at(-1).stage, 'prompt_rejected');
  assert.equal(local.captureDiagnostics.at(-1).error_code, 'capture_paused');
  assert.equal(JSON.stringify(local.captureDiagnostics).includes('SYNTHETIC-PRIVATE-MARKER'), false);
});

test('stores the first ChatGPT prompt while its conversation URL is unknown', async () => {
  let submitted;
  const {send} = worker({localData: {
    installationId: '00000000-0000-4000-8000-000000000098', enabled: true,
    privacyAcceptance: {version: '2026-10-28.2', subject: 'SYN-1', accepted_at: new Date().toISOString()},
    authSession: {access_token: 'synthetic-access-token', employee_code: 'SYN-1',
      expires_at: Math.floor(Date.now() / 1000) + 3600},
    machineAssignment: {person_name: 'Pessoa Sintética', employee_id: 'SYN-1',
      department_code: 'TEST', key_matches: true}
  }, fetchImpl: async (_url, options) => {
    submitted = JSON.parse(options.body);
    return {ok: true, status: 201, json: async () => ({interaction_id})};
  }});
  const result = await send({type: 'capture_prompt', payload: {
    schema_version: '0.1', client_event_id: '00000000-0000-4000-8000-000000000097',
    platform: 'chatgpt_web', project: {capture_status: 'unknown', reason: 'Projeto não identificado'},
    conversation: {capture_status: 'unknown', reason: 'ID da conversa indisponível no momento do envio'},
    prompt: {text: 'Prompt sintético', capture_status: 'observed'},
    attachments: [], attachments_capture_status: 'not_observed', attachments_truncated: false,
    adapter_version: '0.4.6', observed_at: new Date().toISOString()
  }}, {tab: {id: 1}, frameId: 0, url: 'https://chatgpt.com/'});

  assert.equal(result.ok, true);
  assert.deepEqual(submitted.conversation, {capture_status: 'unknown',
    reason: 'ID da conversa indisponível no momento do envio'});
});

test('reports an invalid prompt payload separately from a paused capture', async () => {
  const {send, local} = worker({localData: captureReadyData()});
  local.enabled = true;
  local.captureApiToken = 'synthetic-token-at-least-24-chars';
  local.machineAssignment = {person_name: 'Pessoa Sintética', employee_id: 'SYN-1',
    department_code: 'TEST', key_matches: true};
  const result = await send({type: 'capture_prompt', payload: {prompt: {text: 'SYNTHETIC-PRIVATE-MARKER'}}});

  assert.equal(result.ok, false);
  assert.equal(local.captureDiagnostics.at(-1).stage, 'prompt_rejected');
  assert.equal(local.captureDiagnostics.at(-1).error_code, 'invalid_prompt');
  assert.equal(JSON.stringify(local.captureDiagnostics).includes('SYNTHETIC-PRIVATE-MARKER'), false);
});

test('does not record prompt diagnostics for messages outside the ChatGPT tab', async () => {
  const {send, local} = worker();
  await send({type: 'capture_prompt', payload: {prompt: {text: 'SYNTHETIC-MARKER'}}},
    {tab: {id: 2}, frameId: 0, url: 'https://example.com/'});

  assert.equal(local.captureDiagnostics, undefined);
});

test('keeps actionable diagnostics when blocker health updates repeat', async () => {
  const {send, local} = worker({localData: captureReadyData()});
  local.enabled = true;
  local.captureApiToken = 'synthetic-token-at-least-24-chars';
  local.machineAssignment = {person_name: 'Pessoa Sintética', employee_id: 'SYN-1',
    department_code: 'TEST', key_matches: true};
  await send({type: 'capture_prompt', payload: {prompt: {text: 'SYNTHETIC-MARKER'}}});
  for (let index = 0; index < 40; index++)
    await send({type: 'blocker_health', mainActive: true, blocked: false,
      synchronized: true, machineAssigned: false, authExpired: true, mainBlocked: true});

  assert.equal(local.captureDiagnostics.some(item => item.stage === 'prompt_rejected' &&
    item.error_code === 'invalid_prompt'), true);
  assert.equal(local.captureDiagnostics.filter(item => item.stage === 'blocker_health').length, 1);
  const {at, ...health} = local.captureDiagnostics.find(item => item.stage === 'blocker_health');
  assert.deepEqual(health, {stage: 'blocker_health', main_active: true,
    policy_synchronized: true, page_capture_allowed: false, auth_expired: true,
    protocol_compatible: false, network_gate_blocked: true,
    cloud_configured: true, capture_enabled: true, auth_session_valid: true,
    machine_assignment_complete: true, key_matches: true, subject_bound: true,
    privacy_notice_accepted: true,
    capture_allowed: true});
});

test('reports each capture readiness requirement without exposing credentials', async () => {
  const {send, local} = worker({localData: captureReadyData()});
  local.enabled = true;
  local.captureApiToken = 'synthetic-token-at-least-24-chars';
  local.machineAssignment = {person_name: 'Pessoa SintÃ©tica', employee_id: 'SYN-1',
    department_code: 'TEST', key_matches: true};

  const result = await send({type: 'blocker_health', mainActive: true, blocked: false,
    synchronized: true, machineAssigned: true, authExpired: false, mainBlocked: true});
  assert.equal(result.ok, true, result.error);

  const diagnostic = local.captureDiagnostics.find(item => item.stage === 'blocker_health');
  assert.equal(diagnostic.capture_enabled, true);
  assert.equal(diagnostic.auth_session_valid, true);
  assert.equal(diagnostic.machine_assignment_complete, true);
  assert.equal(diagnostic.key_matches, true);
  assert.equal(diagnostic.subject_bound, true);
  assert.equal(diagnostic.capture_allowed, true);
  assert.equal(JSON.stringify(diagnostic).includes('synthetic-token'), false);

  local.enabled = false;
  await send({type: 'prompt_decision', version: '0.1.2', destination: 'not_approved',
    method: 'click', action: 'BLOCK', primaryRule: 'MACHINE',
    findings: [{rule: 'MACHINE', action: 'BLOCK', count: 1}]});
  const decision = local.captureDiagnostics.find(item => item.stage === 'policy_decision');
  assert.equal(decision.capture_enabled, false);
  assert.equal(decision.auth_session_valid, true);
  assert.equal(decision.machine_assignment_complete, true);
  assert.equal(decision.capture_allowed, false);
});
