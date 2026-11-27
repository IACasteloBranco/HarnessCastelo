import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
import vm from 'node:vm';
import {validConversationObservation} from '../src/background/capture-validation.js';

const source = (await readFile(new URL('../src/background/service-worker.js', import.meta.url), 'utf8'))
  .replace("import {CONFIG} from './config.js';", "const CONFIG = {apiUrl: 'http://127.0.0.1:18081', googleClientId: ''};")
  .replace("import {validConversationObservation} from './capture-validation.js';",
    'const validConversationObservation = globalThis.validConversationObservation;');
const turnKey = '00000000-0000-4000-8000-000000000020';
const interactionId = '00000000-0000-4000-8000-000000000099';
const promptHash = 'a'.repeat(64);

function captureReadyData() {
  return {installationId: '00000000-0000-4000-8000-000000000098', enabled: true,
    privacyAcceptance: {version: '2026-11-16.1', subject: 'SYN-1', accepted_at: new Date().toISOString()},
    authSession: {access_token: 'synthetic-access-token', employee_code: 'SYN-1', department_code: 'TEST',
      expires_at: Math.floor(Date.now() / 1000) + 3600},
    machineAssignment: {person_name: 'Pessoa Sintética', employee_id: 'SYN-1',
      department_code: 'TEST', key_matches: true}};
}

function worker({localData = {}, sessionData = {}, separateStorage = false,
  fetchImpl = async () => {throw new Error('unexpected fetch');}} = {}) {
  const local = {...localData};
  const session = separateStorage ? {...sessionData} : local;
  let onMessage;
  const storage = {
    async get(keys) {
      if (typeof keys === 'string') return {[keys]: local[keys]};
      return Object.fromEntries((Array.isArray(keys) ? keys : Object.keys(local)).map(key => [key, local[key]]));
    },
    async set(values) { Object.assign(local, values); },
    async remove(keys) { for (const key of typeof keys === 'string' ? [keys] : keys) delete local[key]; },
    async setAccessLevel() {}
  };
  const sessionStorage = separateStorage ? {
    async get(keys) {
      if (typeof keys === 'string') return {[keys]: session[keys]};
      return Object.fromEntries((Array.isArray(keys) ? keys : Object.keys(session)).map(key => [key, session[key]]));
    },
    async set(values) { Object.assign(session, values); },
    async remove(keys) { for (const key of typeof keys === 'string' ? [keys] : keys) delete session[key]; },
    async setAccessLevel() {}
  } : storage;
  const chrome = {storage: {local: storage, session: sessionStorage},
    runtime: {getURL: path => `chrome-extension://test/${path}`,
      onMessage: {addListener: listener => {onMessage = listener;}},
      onConnect: {addListener: () => {}}}, alarms: {create: async () => {}, onAlarm: {addListener: () => {}}},
    tabs: {query: async () => []}};
  vm.runInNewContext(source, {chrome, crypto: webcrypto, URL, TextEncoder, Uint8Array,
    AbortSignal, atob: value => Buffer.from(value, 'base64').toString('binary'), btoa,
    fetch: fetchImpl, validConversationObservation, console});
  const sender = {tab: {id: 1}, frameId: 0,
    url: 'https://chatgpt.com/g/g-p-test/c/00000000-0000-4000-8000-000000000030'};
  const send = (message, source = sender) => new Promise(resolve => onMessage(message, source, resolve));
  return {send, local, session};
}

test('temporary password login directs to governance and never starts capture', async () => {
  const {send, local} = worker({fetchImpl: async url => {
    if (url.endsWith('/api/auth/extension/login')) return {ok: true, json: async () => ({must_change_password: true})};
    throw new Error('unexpected fetch');
  }});
  const result = await send({type: 'login', employeeCode: 'SYN-1', password: 'temporary'},
    {url: 'chrome-extension://test/src/popup/popup.html'});
  assert.equal(result.ok, true, result.error);
  assert.equal(result.data.must_change_password, true);
  assert.equal(result.data.password_change_url, 'https://primeiro-login.castelotecnologia.com.br/');
  assert.equal(local.authSession, undefined);
  assert.equal(local.enabled, undefined);
});

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

test('sends the policy engine version and accepts a versioned backend policy', async () => {
  let request;
  const actions = Object.fromEntries(Array.from({length: 9}, (_, index) => [`R${String(index + 1).padStart(2, '0')}`, null]));
  const {send} = worker({localData: captureReadyData(), fetchImpl: async (url, options) => {
    if (!url.endsWith('/api/auth/extension/inspect')) throw new Error('unexpected fetch');
    request = JSON.parse(options.body);
    return {ok: true, status: 200, json: async () => ({action: 'allow', text: null,
      requires_confirmation: false, policy_version: 'governanca-2', categories: [],
      extension_policy: {version: 1, actions}})};
  }});
  const result = await send({type: 'inspect_sensitive_text', text: 'conteúdo sintético'});
  assert.equal(result.ok, true, result.error);
  assert.equal(request.policy_engine_version, '0.1.3');
  assert.equal(result.data.extension_policy.version, 1);
});

test('isolates two active installations for one account through activation, capture, mismatch, and logout', async () => {
  const ids = ['00000000-0000-4000-8000-0000000000a1', '00000000-0000-4000-8000-0000000000b2'];
  const machines = new Map();
  for (const id of ids) {
    const pair = await webcrypto.subtle.generateKey({name: 'ECDSA', namedCurve: 'P-256'}, true, ['sign', 'verify']);
    const privateKey = await webcrypto.subtle.exportKey('jwk', pair.privateKey);
    const jwk = await webcrypto.subtle.exportKey('jwk', pair.publicKey);
    const publicKey = {kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y};
    const decode = value => Buffer.from(value, 'base64url');
    const point = new Uint8Array([4, ...decode(publicKey.x), ...decode(publicKey.y)]);
    const digest = new Uint8Array(await webcrypto.subtle.digest('SHA-256', point));
    const keyFingerprint = [...digest].map(byte => byte.toString(16).padStart(2, '0')).join('');
    machines.set(id, {privateKey, publicKey, keyFingerprint, employee_id: 'SYN-1'});
  }
  const requests = [];
  const revokedTokens = new Set();
  const api = async (url, options = {}) => {
    const path = new URL(url).pathname;
    if (path.endsWith('/api/auth/extension/login'))
      return {ok: true, json: async () => ({...account('SYN-1'),
        access_token: 'synthetic-installation-A-access-token'})};
    if (path.endsWith('/api/auth/extension/logout')) {
      revokedTokens.add(options.headers.Authorization.slice('Bearer '.length));
      return {ok: true, json: async () => ({})};
    }
    if (path.includes('/api/capture/v1/interactions')) {
      const token = options.headers.Authorization.slice('Bearer '.length);
      if (revokedTokens.has(token)) return {ok: false, status: 401, json: async () => ({})};
      const payload = JSON.parse(options.body);
      requests.push({token, ...payload});
      return {ok: true, status: 201, json: async () => ({interaction_id})};
    }
    const machinePath = path.match(/\/v1\/machines\/([^/]+)$/);
    if (machinePath) {
      const machine = machines.get(machinePath[1]);
      return {ok: Boolean(machine), status: machine ? 200 : 404, json: async () => ({
        installation_id: machinePath[1], key_fingerprint: machine?.keyFingerprint,
        person_name: 'Pessoa Sintética', employee_id: machine?.employee_id, department_code: 'TEST'
      })};
    }
    return {ok: true, status: 200, json: async () => ({})};
  };
  const account = employee_code => ({access_token: `synthetic-${employee_code}-access-token`, employee_code,
    expires_at: Math.floor(Date.now() / 1000) + 3600, department_code: 'TEST'});
  const privacyAcceptance = employee_code => ({version: '2026-11-16.1', subject: employee_code,
    accepted_at: new Date().toISOString()});
  const makeInstallation = (id, token, authenticated = true, privacyAccepted = true) => {
    const machine = machines.get(id);
    return worker({separateStorage: true, fetchImpl: api, localData: {installationId: id, enabled: false,
      ...(authenticated ? {authSession: {...account('SYN-1'), access_token: token}} : {}),
      ...(privacyAccepted ? {privacyAcceptance: privacyAcceptance('SYN-1')} : {}),
      machinePrivateKey: machine.privateKey, machinePublicKey: machine.publicKey}, sessionData: {
      machineAssignment: {person_name: 'Pessoa Sintética', employee_id: 'SYN-1',
        department_code: 'TEST', key_matches: true}}});
  };
  const a = makeInstallation(ids[0], 'synthetic-installation-A-access-token', false, false);
  const b = makeInstallation(ids[1], 'synthetic-installation-B-access-token');
  const popup = {url: 'chrome-extension://test/src/popup/popup.html'};
  const page = {tab: {id: 1}, frameId: 0, url: 'https://chatgpt.com/'};

  assert.equal((await a.send({type: 'probe_config'})).data.enabled, false);
  assert.equal((await b.send({type: 'probe_config'})).data.enabled, false);
  const aLogin = await a.send({type: 'login', employeeCode: 'SYN-1', password: 'synthetic'}, popup);
  assert.equal(aLogin.ok, true, aLogin.error);
  assert.equal(a.local.authSession.employee_code, 'SYN-1');
  assert.equal(b.local.authSession.employee_code, 'SYN-1');
  assert.equal((await a.send({type: 'probe_config'})).data.enabled, false);
  assert.equal((await b.send({type: 'probe_config'})).data.enabled, false);
  const aActivation = await a.send({type: 'accept_privacy_notice', version: '2026-11-16.1'}, popup);
  assert.equal(aActivation.ok, true, aActivation.error);
  assert.equal((await a.send({type: 'probe_config'})).data.enabled, true);
  assert.equal((await b.send({type: 'probe_config'})).data.enabled, false);
  const bStatus = await b.send({type: 'status'}, popup);
  assert.equal(bStatus.data.readiness.capture_enabled, false);
  assert.match(bStatus.data.captureBlockReason, /pausada nesta instalação/);

  const bActivation = await b.send({type: 'save', enabled: true}, popup);
  assert.equal(bActivation.ok, true, bActivation.error);
  const prompt = {schema_version: '0.1',
    platform: 'chatgpt_web', project: {capture_status: 'unknown', reason: 'Projeto não identificado'},
    conversation: {capture_status: 'unknown', reason: 'ID da conversa indisponível'},
    prompt: {text: 'Prompt sintético', capture_status: 'observed'}, attachments: [],
    attachments_capture_status: 'not_observed', attachments_truncated: false, adapter_version: '0.4.6',
    observed_at: new Date().toISOString()};
  const [aCapture, bCapture] = await Promise.all([
    a.send({type: 'capture_prompt', payload: {...prompt, client_event_id: '00000000-0000-4000-8000-0000000000a3'}}, page),
    b.send({type: 'capture_prompt', payload: {...prompt, client_event_id: '00000000-0000-4000-8000-0000000000b4'}}, page)
  ]);
  assert.equal(aCapture.ok, true, aCapture.error);
  assert.equal(bCapture.ok, true, bCapture.error);
  assert.deepEqual(requests.map(({device_installation_id, token}) => [device_installation_id, token])
    .sort(([first], [second]) => first.localeCompare(second)), [
    [ids[0], 'synthetic-installation-A-access-token'], [ids[1], 'synthetic-installation-B-access-token']
  ].sort(([first], [second]) => first.localeCompare(second)));

  machines.get(ids[1]).employee_id = 'SYN-OTHER';
  const mismatched = await b.send({type: 'status'}, popup);
  assert.equal(mismatched.data.readiness.installation_assigned, true);
  assert.equal(mismatched.data.readiness.identity_matches, false);
  assert.match(mismatched.data.captureBlockReason, /não corresponde/);
  assert.equal((await b.send({type: 'capture_prompt', payload: prompt}, page)).ok, false);

  await a.send({type: 'logout'}, {url: 'chrome-extension://test/src/popup/popup.html'});
  assert.equal(a.local.authSession, undefined);
  assert.equal(b.local.authSession.employee_code, 'SYN-1');
  assert.equal((await b.send({type: 'probe_config'})).data.enabled, false);
  machines.get(ids[1]).employee_id = 'SYN-1';
  await b.send({type: 'status'}, popup);
  assert.equal((await b.send({type: 'capture_prompt', payload: {...prompt,
    client_event_id: '00000000-0000-4000-8000-0000000000b5'}}, page)).ok, true);
});

test('stores the first ChatGPT prompt while its conversation URL is unknown', async () => {
  let submitted;
  const {send} = worker({localData: {
    installationId: '00000000-0000-4000-8000-000000000098', enabled: true,
    privacyAcceptance: {version: '2026-11-16.1', subject: 'SYN-1', accepted_at: new Date().toISOString()},
    authSession: {access_token: 'synthetic-access-token', employee_code: 'SYN-1', department_code: 'TEST',
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

  assert.equal(result.ok, true, result.error);
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
      synchronized: true, captureAllowed: false, authExpired: true, mainBlocked: true});

  assert.equal(local.captureDiagnostics.some(item => item.stage === 'prompt_rejected' &&
    item.error_code === 'invalid_prompt'), true);
  assert.equal(local.captureDiagnostics.filter(item => item.stage === 'blocker_health').length, 1);
  const {at, ...health} = local.captureDiagnostics.find(item => item.stage === 'blocker_health');
  assert.deepEqual(health, {stage: 'blocker_health', main_active: true,
    policy_synchronized: true, page_capture_allowed: false, auth_expired: true,
    protocol_compatible: false, network_gate_blocked: true,
    server_configured: true, authenticated: true, installation_assigned: true,
    identity_matches: true, capture_enabled: true, privacy_accepted: true,
    capture_allowed: true});
});

test('reports each capture readiness requirement without exposing credentials', async () => {
  const {send, local} = worker({localData: captureReadyData()});
  local.enabled = true;
  local.captureApiToken = 'synthetic-token-at-least-24-chars';
  local.machineAssignment = {person_name: 'Pessoa SintÃ©tica', employee_id: 'SYN-1',
    department_code: 'TEST', key_matches: true};

  const result = await send({type: 'blocker_health', mainActive: true, blocked: false,
    synchronized: true, captureAllowed: true, authExpired: false, mainBlocked: true});
  assert.equal(result.ok, true, result.error);

  const diagnostic = local.captureDiagnostics.find(item => item.stage === 'blocker_health');
  assert.equal(diagnostic.capture_enabled, true);
  assert.equal(diagnostic.authenticated, true);
  assert.equal(diagnostic.installation_assigned, true);
  assert.equal(diagnostic.identity_matches, true);
  assert.equal(diagnostic.capture_allowed, true);
  assert.equal(JSON.stringify(diagnostic).includes('synthetic-token'), false);

  local.enabled = false;
  await send({type: 'prompt_decision', version: '0.1.3', destination: 'not_approved',
    method: 'click', action: 'BLOCK', primaryRule: 'MACHINE',
    findings: [{rule: 'MACHINE', action: 'BLOCK', count: 1}]});
  const decision = local.captureDiagnostics.find(item => item.stage === 'policy_decision');
  assert.equal(decision.capture_enabled, false);
  assert.equal(decision.authenticated, true);
  assert.equal(decision.installation_assigned, true);
  assert.equal(decision.capture_allowed, false);
});

test('reports capture readiness when no extension session is stored', async () => {
  const {send} = worker({localData: {enabled: true}});
  const result = await send({type: 'status'},
    {url: 'chrome-extension://test/src/popup/popup.html'});

  assert.equal(result.ok, true, result.error);
  assert.equal(result.data.authenticated, false);
  assert.equal(result.data.captureAllowed, false);
});

test('rejects capture actions cleanly when nobody is logged in', async () => {
  const {send, local} = worker({localData: {enabled: false}});
  const popup = {url: 'chrome-extension://test/src/popup/popup.html'};
  for (const message of [
    {type: 'save', enabled: true},
    {type: 'accept_privacy_notice', version: '2026-11-16.1'}
  ]) {
    const result = await send(message, popup);
    assert.equal(result.ok, false);
    assert.match(result.error, /entre|sessão/i);
    assert.doesNotMatch(result.error, /Cannot read properties|undefined/);
  }
  assert.equal(local.enabled, false);
});

test('returns a useful error after a failed login request', async () => {
  const {send, local} = worker({fetchImpl: async () => { throw new Error('network offline'); }});
  const popup = {url: 'chrome-extension://test/src/popup/popup.html'};
  const login = await send({type: 'login', employeeCode: 'SYN-1', password: 'synthetic'}, popup);
  assert.equal(login.ok, false);
  assert.match(login.error, /network offline/);
  const status = await send({type: 'status'}, popup);
  assert.equal(status.ok, true, status.error);
  assert.equal(status.data.authenticated, false);
  assert.equal(local.authSession, undefined);
});

test('keeps the popup usable with an expired or malformed stored session', async () => {
  for (const authSession of [
    {access_token: 'expired-token', expires_at: 1},
    {access_token: 'malformed-token', expires_at: 'invalid'}
  ]) {
    const {send, local} = worker({localData: {enabled: true, authSession}});
    const result = await send({type: 'status'},
      {url: 'chrome-extension://test/src/popup/popup.html'});
    assert.equal(result.ok, true, result.error);
    assert.equal(result.data.authenticated, false);
    assert.equal(result.data.captureAllowed, false);
    assert.equal(local.authSession, undefined);
  }
});

test('keeps the popup usable when renewal is revoked or the backend is offline', async () => {
  for (const response of [
    {status: 401},
    null
  ]) {
    const data = captureReadyData();
    const {send, local} = worker({localData: data, fetchImpl: async () => {
      if (response) return response;
      throw new Error('backend offline');
    }});
    const result = await send({type: 'status'},
      {url: 'chrome-extension://test/src/popup/popup.html'});
    assert.equal(result.ok, true, result.error);
    assert.equal(result.data.captureAllowed, false);
    assert.equal(result.data.authenticated, !response);
    assert.equal(local.authSession === undefined, Boolean(response));
  }
});

test('renews an active extension session without turning capture off', async () => {
  const data = captureReadyData();
  data.authSession.expires_at = Math.floor(Date.now() / 1000) + 24 * 60 * 60;
  const extended = Math.floor(Date.now() / 1000) + 90 * 24 * 60 * 60;
  let renewals = 0;
  const {send, local} = worker({localData: data, fetchImpl: async url => {
    assert.match(url, /\/api\/auth\/extension\/renew$/);
    renewals++;
    return {ok: true, status: 200, json: async () => ({expires_at: extended})};
  }});
  const result = await send({type: 'blocker_health', mainActive: true, blocked: false,
    synchronized: true, captureAllowed: true, authExpired: false, mainBlocked: true});
  assert.equal(result.ok, true, result.error);
  assert.equal(local.authSession.expires_at, extended);
  assert.equal(local.enabled, true);
  assert.equal(renewals, 1);
});
