const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = path.join(__dirname, '..', 'public', 'app.js');
function element() {
  return {
    hidden: false, value: '', textContent: '', children: [], listeners: {}, dataset: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; },
    append(...nodes) { this.children.push(...nodes); },
    setAttribute(name, value) { this[name] = value; },
    reset() { this.value = ''; },
    async fire(type) { return this.listeners[type]({ preventDefault() {}, currentTarget: this }); },
  };
}
async function portal(responses) {
  const ids = {};
  const calls = [];
  const location = { pathname: '/' };
  const history = { replaceState(_state, _title, url) { location.pathname = url; } };
  const document = {
    getElementById(id) { return ids[id] ||= element(); },
    createElement() { return element(); },
  };
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    const result = responses[url];
    const value = typeof result === 'function' ? await result(options) : result;
    if (value === undefined) throw Error(`Unexpected request: ${url}`);
    return { ok: typeof value.status !== 'number' || value.status < 400,
      status: typeof value.status === 'number' ? value.status : 200,
      json: async () => value.body || value };
  };
  vm.runInNewContext(fs.readFileSync(script, 'utf8'), { document, fetch, URLSearchParams, location, history, console });
  await new Promise(resolve => setImmediate(resolve));
  return { ids, calls, location, el: id => document.getElementById(id) };
}

test('first-login password change is a dedicated gate before any analytics', async () => {
  const p = await portal({ '/api/auth/me': { status: 401, body: { detail: 'authentication required' } },
    '/api/auth/login': { must_change_password: true } });
  p.el('employee-code').value = 'GOV001';
  p.el('password').value = 'temporary';
  await p.el('login-form').fire('submit');
  assert.equal(p.el('change-screen').hidden, false);
  assert.equal(p.el('portal-screen').hidden, true);
  assert.equal(p.location.pathname, '/change-password');
  assert.deepEqual(p.calls.map(call => call.url), ['/api/auth/me', '/api/auth/login']);
});

test('password change unlocks portal only after server confirms it', async () => {
  let changed = false;
  const p = await portal({
    '/api/auth/me': () => ({ must_change_password: !changed, role: 'governance' }),
    '/api/auth/change-password': () => { changed = true; return { must_change_password: false }; },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 2 }, by_department: [] },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
  });
  assert.equal(p.el('change-screen').hidden, false);
  assert.deepEqual(p.calls.map(call => call.url), ['/api/auth/me']);
  p.el('current-password').value = 'temporary';
  p.el('new-password').value = 'long-new-password';
  await p.el('change-form').fire('submit');
  assert.equal(p.el('change-screen').hidden, true);
  assert.equal(p.el('portal-screen').hidden, false);
  assert.equal(p.location.pathname, '/');
  assert.equal(p.calls[1].url, '/api/auth/change-password');
  assert.equal(JSON.parse(p.calls[1].options.body).current_password, 'temporary');
});

test('analytics renders only metadata as text and filters interactions', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': {
      totals: { interactions: 3, responses: 2 }, by_department: [] },
    '/api/capture/v1/admin/analytics/departments': { departments: [{
      department_code: 'FIN', department_name: '<img src=x onerror=alert(1)>',
      platform: 'chatgpt_web', interactions: 3, responses: 2 }] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/capture/v1/admin/analytics/interactions?department_code=FIN': { items: [{
      interaction_id: 'interaction-1', employee_id: 'EMP1', department_code: 'FIN',
      platform: 'chatgpt_web', status: 'complete', received_at: '2026-11-01T00:00:00Z',
      prompt: 'NEVER RENDER CONTENT',
    }], total: 1 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
  });
  assert.match(p.el('summary').textContent, /3/);
  assert.equal(p.el('departments').children[0].children[0].textContent,
    '<img src=x onerror=alert(1)>');
  p.el('department-code').value = 'FIN';
  await p.el('search-form').fire('submit');
  assert.equal(p.el('interactions').children.length, 1);
  assert.equal(JSON.stringify(p.el('interactions').children).includes('NEVER RENDER CONTENT'), false);
  assert.equal(p.calls.at(-1).url, '/api/capture/v1/admin/analytics/interactions?department_code=FIN');
});

test('investigation fixes its subject before approval and detail is requested', async () => {
  let state = 'pending';
  let resolveDetail;
  let detailResponse = { prompt: { text: '<img src=x onerror=alert(1)>' }, responses: [{ text: 'answer' }] };
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 1, responses: 1 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [{
      interaction_id: '00000000-0000-0000-0000-000000000001', employee_id: 'EMP1',
      department_code: 'FIN', platform: 'chatgpt_web', status: 'complete', received_at: 'now',
    }], total: 1 },
    '/api/governance/investigations': () => ({ investigations: [{ id: 'case-1',
      purpose: '<script>bad()</script>', status: state, viewers: ['EMP1'], requested_by: 'GOV2',
      can_approve: state === 'pending', can_reject: state === 'pending', can_use: state === 'approved',
      target_employee_code: 'EMP1', expires_at: '2099-01-01T00:00:00Z',
    }] }),
    '/api/governance/investigations/case-1/decision/approve': () => { state = 'approved'; return { status: state }; },
    '/api/capture/v1/interactions/00000000-0000-0000-0000-000000000001?investigation_id=case-1': () => detailResponse,
  });
  const item = p.el('interactions').children[0];
  assert.equal(item.children.at(-1).listeners.click, undefined);
  assert.match(p.el('investigations').children[0].children[0].textContent, /^<script>bad\(\)<\/script>/);
  await p.el('investigations').children[0].children[1].fire('click');
  await p.el('investigations').children[0].children.at(-1).fire('click');
  await p.el('interactions').children[0].children.at(-1).fire('click');
  assert.equal(p.el('detail').children[0].textContent, '<img src=x onerror=alert(1)>');
  detailResponse = new Promise(resolve => { resolveDetail = resolve; });
  const pendingDetail = p.el('interactions').children[0].children.at(-1).fire('click');
  await p.el('search-form').fire('submit');
  resolveDetail({ prompt: { text: 'STALE PRIVATE CONTENT' }, responses: [] });
  await pendingDetail;
  assert.equal(p.el('detail').children.length, 0);
});

test('machine approval lists pending assignments and respects server eligibility', async () => {
  let items = [{ installation_id: 'machine-1', requested_employee_id: 'EMP1',
    person_name: '<b>person</b>', department_code: 'FIN', can_approve: true },
  { installation_id: 'machine-2', requested_employee_id: 'EMP2',
    person_name: 'Other', department_code: 'FIN', can_approve: false }];
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': () => ({ items }),
    '/api/capture/v1/admin/machines/machine-1/assignment-request/approve': () => {
      items = items.slice(1); return { status: 'approved' };
    },
  });
  assert.equal(p.el('machines').children[0].children[0].textContent, 'machine-1 · EMP1 · <b>person</b> · FIN');
  assert.equal(p.el('machines').children[1].children.some(child => child.textContent === 'Aprovar'), false);
  await p.el('machines').children[0].children[1].fire('click');
  assert.equal(p.el('machines').children.length, 1);
});

test('standalone document has dedicated password gate and privacy notice', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  for (const id of ['login-screen', 'change-screen', 'portal-screen', 'login-form', 'change-form',
    'search-form', 'investigation-form', 'machines', 'detail']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /href="\.\/privacidade\.html"/);
  assert.match(html, /id="change-screen"[^>]*hidden/);
  assert.match(html, /id="portal-screen"[^>]*hidden/);
  assert.doesNotMatch(html, /convite|ativação de conta/i);
  const notice = fs.readFileSync(path.join(__dirname, '..', 'public', 'privacidade.html'), 'utf8');
  assert.match(notice, /Aviso de Privacidade/);
  assert.match(notice, /investigaç/);
});

test('logout clears sensitive content and returns to login', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
    '/api/auth/logout': { status: 204 },
  });
  p.el('detail').append(Object.assign(element(), { textContent: 'private prompt' }));
  await p.el('logout').fire('click');
  assert.equal(p.el('detail').children.length, 0);
  assert.equal(p.el('portal-screen').hidden, true);
  assert.equal(p.el('login-screen').hidden, false);
  assert.equal(p.calls.at(-1).url, '/api/auth/logout');
});

test('older filtered interaction response cannot replace newer results', async () => {
  let resolveOld;
  const old = new Promise(resolve => { resolveOld = resolve; });
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/capture/v1/admin/analytics/interactions?department_code=OLD': () => old,
    '/api/capture/v1/admin/analytics/interactions?department_code=NEW': { items: [
      { interaction_id: 'new', employee_id: 'EMP' }], total: 1 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
  });
  p.el('department-code').value = 'OLD';
  const pending = p.el('search-form').fire('submit');
  p.el('department-code').value = 'NEW';
  await p.el('search-form').fire('submit');
  resolveOld({ items: [{ interaction_id: 'old', employee_id: 'EMP' }], total: 1 });
  await pending;
  assert.equal(p.el('interactions').children[0].children[0].textContent, 'new');
});

test('UTC period applies to summary, departments, and interactions', async () => {
  const period = 'from=2026-11-01T10%3A00%3A00.000Z&to=2026-11-02T10%3A00%3A00.000Z';
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    [`/api/capture/v1/admin/analytics/summary?${period}`]: { totals: { interactions: 2, responses: 1 } },
    [`/api/capture/v1/admin/analytics/departments?${period}`]: { departments: [] },
    [`/api/capture/v1/admin/analytics/interactions?${period}`]: { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
  });
  p.el('from-date').value = '2026-11-01T10:00';
  p.el('to-date').value = '2026-11-02T10:00';
  await p.el('search-form').fire('submit');
  assert.equal(p.el('summary').textContent.includes('2'), true);
  assert.deepEqual(p.calls.slice(-3).map(call => call.url).sort(), [
    `/api/capture/v1/admin/analytics/summary?${period}`,
    `/api/capture/v1/admin/analytics/departments?${period}`,
    `/api/capture/v1/admin/analytics/interactions?${period}`,
  ].sort());
});

test('request submits purpose and viewers and rejection uses decision route', async () => {
  let created = false;
  let rejected = false;
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
    '/api/governance/investigations': options => {
      if (options.method === 'POST') { created = true; return { id: 'case-2' }; }
      return { investigations: created && !rejected ? [{ id: 'case-2', purpose: 'Suspeita documentada de vazamento',
        status: 'pending', requested_by: 'OTHER', viewers: ['GOV1'], can_approve: true, can_reject: true }] : [] };
    },
    '/api/governance/investigations/case-2/decision/reject': () => {
      rejected = true; return { status: 'rejected' };
    },
  });
  p.el('purpose').value = 'Suspeita documentada de vazamento';
  p.el('viewers').value = 'GOV1, GOV2';
  p.el('investigation-employee-code').value = 'EMP1';
  await p.el('investigation-form').fire('submit');
  const request = p.calls.find(call => call.url === '/api/governance/investigations' && call.options.method === 'POST');
  assert.deepEqual(JSON.parse(request.options.body), {
    purpose: 'Suspeita documentada de vazamento', viewers: ['GOV1', 'GOV2'], employee_code: 'EMP1',
  });
  await p.el('investigations').children[0].children.at(-1).fire('click');
  assert.equal(rejected, true);
});

test('legacy investigation without subject can be rejected but not approved', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
    '/api/governance/investigations': { investigations: [{ id: 'case-legacy', purpose: 'Legacy case',
      status: 'pending', viewers: ['GOV1'], requested_by: 'GOV2', target_employee_code: null,
      can_approve: false, can_reject: true }] },
  });
  const buttons = p.el('investigations').children[0].children.filter(child => child.type === 'button');
  assert.deepEqual(buttons.map(child => child.textContent), ['Rejeitar']);
});

test('logout prevents a pending analytics response from restoring private data', async () => {
  let resolveSummary;
  let slow = false;
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': () => slow
      ? new Promise(resolve => { resolveSummary = resolve; })
      : { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
    '/api/auth/logout': { status: 204 },
  });
  slow = true;
  const pending = p.el('search-form').fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  await p.el('logout').fire('click');
  resolveSummary({ totals: { interactions: 99, responses: 1 } });
  await pending;
  assert.equal(p.el('summary').textContent, '');
  assert.equal(p.el('portal-screen').hidden, true);
});
