const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = path.join(__dirname, '..', 'public', 'app.js');
function element() {
  return {
    hidden: false, value: '', textContent: '', children: [], listeners: {}, dataset: {}, style: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    replaceChildren(...nodes) { this.children = nodes; this.textContent = ''; this.value = ''; },
    append(...nodes) { this.children.push(...nodes); },
    querySelectorAll(selector) {
      const matches = [];
      const visit = node => { if (selector === 'select' && node.tagName === 'select') matches.push(node); node.children?.forEach(visit); };
      this.children.forEach(visit);
      return matches;
    },
    setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
    reset() { this.value = ''; },
    async fire(type) { return this.listeners[type]({ preventDefault() {}, currentTarget: this }); },
  };
}
async function portal(responses, pathname = '/', confirmResult = true) {
  const ids = {};
  const calls = [];
  const confirmations = [];
  const location = { pathname, replace(url) { this.href = url; } };
  const history = { replaceState(_state, _title, url) { location.pathname = url; } };
  const document = {
    body: { classList: { toggle() {} } },
    getElementById(id) {
      const target = ids[id] ||= element();
      if (id === 'tv-department' && !target.children.length) target.append(Object.assign(element(), { value: '', textContent: 'Todos' }));
      return target;
    },
    createElement(tagName) { return Object.assign(element(), { tagName }); },
  };
  const fetch = async (url, options = {}) => {
    calls.push({ url, options });
    const result = responses[url] ?? Object.entries(responses).sort(([a], [b]) => b.length - a.length)
      .find(([key]) => url.startsWith(key))?.[1] ??
      (url === '/api/auth/governance/departments' ? { departments: [] } :
        url === '/api/auth/governance/backup-status' ? { state: 'unknown', last_success_at: null } :
        url === '/api/capture/v1/admin/machines/health' ? { items: [] } :
        url === '/api/auth/governance/heartbeat-settings' ? { interval_hours: 12, stale_after_hours: 72 } :
      url === '/api/auth/governance/policies' ? { extension: { version: '0.1.2', destination: 'not_approved', rules: [], decision_counts: 'local_only', warning_rules: ['R05', 'R06'] },
            server_inspection: { version: 'governanca-2', categories: [] } } : undefined);
    const value = typeof result === 'function' ? await result(options) : result;
    if (value === undefined) throw Error(`Unexpected request: ${url}`);
    return { ok: typeof value.status !== 'number' || value.status < 400,
      status: typeof value.status === 'number' ? value.status : 200,
      json: async () => value.body || value };
  };
  vm.runInNewContext(fs.readFileSync(script, 'utf8'), {
    document, fetch, URLSearchParams, location, history, console, Date, Intl,
    confirm(message) { confirmations.push(message); return confirmResult; },
    setInterval() { return 1; }, clearInterval() {}, setTimeout() { return 1; }, clearTimeout() {},
  });
  await new Promise(resolve => setImmediate(resolve));
  return { ids, calls, confirmations, location, el: id => document.getElementById(id) };
}

test('governance portal redirects temporary-password sessions to the dedicated host', async () => {
  const p = await portal({ '/api/auth/me': { status: 401, body: { detail: 'authentication required' } },
    '/api/auth/login': { must_change_password: true } });
  p.el('employee-code').value = 'GOV001';
  p.el('password').value = 'temporary';
  await p.el('login-form').fire('submit');
  assert.equal(p.el('portal-screen').hidden, true);
  assert.equal(p.location.href, 'https://primeiro-login.castelotecnologia.com.br/');
  assert.deepEqual(p.calls.map(call => call.url), ['/api/auth/me', '/api/auth/login']);
});

test('governance document no longer contains the password-change form', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  assert.doesNotMatch(html, /id="change-form"|Senha temporária|Troca obrigatória/);
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
  const department = p.el('departments').children[0];
  assert.equal(department.children[0].textContent, '<img src=x onerror=alert(1)>');
  assert.deepEqual(department.children[1].children.map(group =>
    group.children.map(cell => cell.textContent)), [
    ['Plataforma', 'chatgpt_web'], ['Interações', '3'], ['Respostas', '2'],
  ]);
  p.el('department-code').value = 'FIN';
  await p.el('search-form').fire('submit');
  assert.equal(p.el('interactions').children.length, 1);
  assert.equal(JSON.stringify(p.el('interactions').children).includes('NEVER RENDER CONTENT'), false);
  assert.equal(p.calls.at(-1).url, '/api/capture/v1/admin/analytics/interactions?department_code=FIN');
});

test('approved access scopes content and prevents stale detail from returning', async () => {
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
    '/api/governance/investigations': { investigations: [{ id: 'case-1',
      purpose: '<script>bad()</script>', status: 'approved', viewers: ['GOV1'], requested_by: 'GOV1',
      can_approve: false, can_reject: false, can_use: true,
      target_employee_code: 'EMP1', expires_at: '2099-01-01T00:00:00Z',
    }] },
    '/api/capture/v1/interactions/00000000-0000-0000-0000-000000000001?investigation_id=case-1': () => detailResponse,
  });
  const item = p.el('interactions').children[0];
  assert.equal(item.children.at(-1).listeners.click, undefined);
  assert.match(p.el('investigations').children[0].children[0].textContent, /^<script>bad\(\)<\/script>/);
  assert.deepEqual(p.el('investigations').children[0].children
    .filter(child => child.type === 'button').map(button => button.textContent), ['Usar acesso']);
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

test('governance creates collaborator credentials without machine approval controls', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/auth/governance/accounts': { employee_code: 'EMP3', temporary_password: 'temp-unique', must_change_password: true },
  });
  p.el('account-code').value = 'EMP3';
  p.el('account-name').value = 'Pessoa Teste';
  p.el('account-department').value = 'FIN';
  await p.el('account-form').fire('submit');
  assert.match(p.el('account-result').textContent, /temp-unique/);
  assert.equal(p.el('copy-temporary-password').hidden, false);
  assert.equal(p.calls.at(-1).url, '/api/auth/governance/accounts');
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  assert.doesNotMatch(html, /Aprovações de máquinas|Atualizar identificação|Solicitar vínculo/);
});

test('governance resets a collaborator password only after confirmation', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/auth/governance/accounts/reset-password': {
      employee_code: 'EMP3', temporary_password: 'reset-temp', must_change_password: true,
    },
  });
  p.el('reset-account-code').value = 'EMP3';
  await p.el('reset-account-form').fire('submit');
  const reset = p.calls.at(-1);
  assert.equal(reset.url, '/api/auth/governance/accounts/reset-password');
  assert.deepEqual(JSON.parse(reset.options.body), { employee_code: 'EMP3' });
  assert.match(p.confirmations[0], /EMP3/);
  assert.match(p.el('account-result').textContent, /reset-temp/);
  assert.equal(p.el('copy-temporary-password').hidden, false);
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  assert.match(html, /id="reset-account-form"/);
});

test('canceling a password reset sends no reset request', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
  }, '/', false);
  p.el('reset-account-code').value = 'EMP3';
  await p.el('reset-account-form').fire('submit');
  assert.equal(p.calls.some(call => call.url === '/api/auth/governance/accounts/reset-password'), false);
});

test('a password reset response arriving after logout does not reveal the temporary password', async () => {
  let resolveReset;
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/governance/investigations': { investigations: [] },
    '/api/auth/governance/accounts/reset-password': () => new Promise(resolve => { resolveReset = resolve; }),
    '/api/auth/logout': { status: 204 },
  });
  p.el('reset-account-code').value = 'EMP3';
  const pending = p.el('reset-account-form').fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  await p.el('logout').fire('click');
  resolveReset({ employee_code: 'EMP3', temporary_password: 'must-not-reappear', must_change_password: true });
  await pending;
  assert.equal(p.el('portal-screen').hidden, true);
  assert.equal(p.el('account-result').textContent, '');
  assert.equal(p.el('copy-temporary-password').hidden, true);
});

test('TV dashboard loads prompts and responses with employee and department', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/auth/governance/backup-status': { state: 'fresh', last_success_at: '2026-11-26T02:55:00Z' },
    '/api/auth/governance/policies': { extension: { version: '0.1.2' },
      server_inspection: { version: 'governanca-2' } },
    '/api/capture/v1/admin/analytics/tv': { totals: { interactions: 1, complete_responses: 1, employees: 1, departments: 1,
      incomplete_responses: 0, last_activity_at: null },
      by_department: [{ department_code: 'FIN', department_name: 'Fiscal', interactions: 1 }], by_platform: [] },
    '/api/capture/v1/admin/analytics/tv?department_code=FIN': { totals: { interactions: 1, complete_responses: 1, employees: 1, departments: 1,
      incomplete_responses: 0, last_activity_at: null },
      by_department: [{ department_code: 'FIN', department_name: 'Fiscal', interactions: 1 }], by_platform: [] },
    '/api/capture/v1/admin/analytics/tv-interactions': { items: [{ employee_id: 'CB-1', person_name: 'Pessoa teste',
      department_name: 'Fiscal', platform: 'chatgpt_web', prompt: { text: 'prompt sintético' },
      responses: [{ text: 'resposta sintética' }] }] },
    '/api/capture/v1/admin/analytics/tv-interactions?department_code=FIN': { items: [{ employee_id: 'CB-1',
      person_name: 'Pessoa teste', department_code: 'FIN', department_name: 'Fiscal', platform: 'chatgpt_web',
      prompt: { text: 'prompt sintético' }, responses: [{ text: 'resposta sintética' }] }] },
  }, '/tv');
  assert.match(p.el('tv-content-status').textContent, /interações recebidas/);
  assert.match(p.el('tv-interactions-list').children[0].children[0].textContent, /Pessoa teste · Fiscal/);
  assert.match(p.el('tv-interactions-list').children[0].children[1].textContent, /prompt sintético/);
  assert.match(p.el('tv-interactions-list').children[0].children[2].textContent, /resposta sintética/);
  assert.ok(p.calls.some(call => call.url === '/api/capture/v1/admin/analytics/tv-interactions'));
  assert.equal(p.el('tv-department').children[1].textContent, 'Fiscal');
  p.el('tv-department').value = 'FIN';
  await p.el('tv-department').fire('change');
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(p.calls.some(call => call.url.startsWith('/api/capture/v1/admin/analytics/tv?') && call.url.includes('department_code=FIN')));
  assert.ok(p.calls.some(call => call.url.includes('/api/capture/v1/admin/analytics/tv-interactions?department_code=FIN')), JSON.stringify(p.calls.map(call => call.url)));
  assert.equal(p.el('tv-interactions').textContent, '1');
  assert.equal(p.el('tv-complete').textContent, '1');
  assert.match(p.el('tv-backup-status').textContent, /Recente/);
  assert.match(p.el('tv-policy-version').textContent, /política v0.*governanca-2/);
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  assert.doesNotMatch(html, /tv-request-content|Solicitar exibição/);
});

test('governance portal uses a new cache key for its application script', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  assert.match(html, /app\.js\?v=20261127-heartbeat-settings/);
});

test('governance navigation buttons and pages match the ids used by the app', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  for (const id of ['nav-overview', 'nav-health', 'nav-policies', 'page-overview', 'page-health', 'page-policies']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
});

test('health view uses real daily capture totals and hides department codes', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 2, responses: 2 } },
    '/api/capture/v1/admin/analytics/summary?': {
      totals: { interactions: 4, complete_responses: 3, incomplete_responses: 1 },
      by_department: [{ department_code: 'FIN-SECRET', department_name: 'Fiscal', last_activity_at: '2026-11-26T02:55:00Z' }],
    },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/auth/governance/departments': { departments: [{ code: 'FIN-SECRET', name: 'Fiscal' }] },
    '/api/governance/investigations': { investigations: [] },
  });
  assert.equal(p.el('activity-interactions').textContent, '4');
  assert.equal(p.el('activity-complete').textContent, '3');
  assert.equal(p.el('activity-incomplete').textContent, '1');
  assert.match(p.el('activity-last-event').textContent, /Última atividade registrada hoje/);
  assert.equal(p.el('department-code').children[1].textContent, 'Fiscal');
  assert.equal(p.el('department-code').children[1].value, 'FIN-SECRET');
  assert.doesNotMatch(fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8'), /25 nov 2026|8 exemplos|50 instalações fictícias|v1 · aprovada/);
});

test('health and policy views render authenticated backend status and policy sources', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/auth/governance/backup-status': { state: 'fresh', last_success_at: '2026-11-26T02:55:00Z' },
    '/api/auth/governance/policies': {
      extension: { version: '0.1.2', destination: 'not_approved', actions: ['ALLOW', 'WARN', 'REVIEW', 'BLOCK'],
        warning_rules: ['R05', 'R06'], decision_counts: 'local_only',
        rules: [{ id: 'R01', label: 'Chave privada', effect: 'Bloqueia o envio.' }] },
      server_inspection: { version: 'governanca-2', policy_version: 3,
        categories: [{ name: 'CNPJ', action: 'allow' }, { name: 'CPF', action: 'mask' }] },
    },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/auth/governance/departments': { departments: [] },
    '/api/governance/investigations': { investigations: [] },
  });
  await p.el('nav-health').fire('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.el('backup-status').textContent, 'Último sucesso dentro de 97 horas');
  assert.match(p.el('backup-last-success').textContent, /25\/11\/2026/);
  await p.el('nav-policies').fire('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.el('extension-policy-version').textContent, 'Política v0 · motor 0.1.2');
  assert.match(p.el('policy-action-summary').textContent, /avisa e permite continuar/);
  assert.match(p.el('policy-rules').children[0].textContent, /R01.*Chave privada.*Bloqueia/);
  assert.match(p.el('server-policy-version').textContent, /governanca-2/);
  assert.equal(p.el('server-policy-controls').querySelectorAll('select')[0].value, 'allow');
  assert.equal(p.el('server-policy-controls').querySelectorAll('select')[1].value, 'mask');
});

test('governance can save behavior changes with the current policy version', async () => {
  const actions = Object.fromEntries(Array.from({ length: 9 }, (_, index) => [`R${String(index + 1).padStart(2, '0')}`, null]));
  let savedBody;
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/auth/governance/policies': async options => {
      if (options.method === 'PUT') { savedBody = JSON.parse(options.body); return { version: 5, actions: savedBody.actions }; }
      return { extension: { version: '0.1.2', policy_version: 4, configured_actions: actions,
        actions: ['ALLOW', 'WARN', 'REVIEW', 'BLOCK'], destination: 'not_approved', warning_rules: [],
        decision_counts: 'local_only', rules: [{ id: 'R01', label: 'Chave privada', effect: 'Bloqueia o envio.' }] },
        server_inspection: { version: 'governanca-2', categories: [] } };
    },
  });
  await p.el('nav-policies').fire('click');
  await new Promise(resolve => setImmediate(resolve));
  const select = p.el('policy-controls').querySelectorAll('select')[0];
  select.value = 'WARN';
  await p.el('policy-form').fire('submit');
  assert.equal(savedBody.expected_version, 4);
  assert.equal(savedBody.actions.R01, 'WARN');
  assert.equal(p.el('policy-save-status').textContent, 'Política v5 salva e auditada.');
});

test('first-login document owns the password-change forms and links back to governance', () => {
  const html = fs.readFileSync(path.join(__dirname, '..', 'public', 'index.html'), 'utf8');
  for (const id of ['login-screen', 'portal-screen', 'login-form',
    'search-form', 'investigation-form', 'account-form', 'export-interactions', 'detail',
    'tv-interactions-list']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.doesNotMatch(html, /id="change-form"|Senha temporária|Troca obrigatória/);
  assert.match(html, /id="portal-screen"[^>]*hidden/);
  assert.doesNotMatch(html, /convite|ativação de conta/i);
  const notice = fs.readFileSync(path.join(__dirname, '..', 'public', 'privacidade.html'), 'utf8');
  assert.match(notice, /Aviso de Privacidade/);
  assert.match(notice, /investigaç/);
  const firstLogin = fs.readFileSync(path.join(__dirname, '..', 'public', 'first-login.html'), 'utf8');
  assert.match(firstLogin, /id="change-form"/);
  assert.match(firstLogin, /id="confirm-password"/);
  assert.match(firstLogin, /id="governance-link"[^>]*hidden/);
  const firstLoginScript = fs.readFileSync(path.join(__dirname, '..', 'public', 'first-login.js'), 'utf8');
  assert.match(firstLoginScript, /change-password/);
  assert.match(firstLogin, /governanca\.castelotecnologia\.com\.br/);
});

test('first-login form confirms the new password before submitting it', async () => {
  const elements = {};
  const calls = [];
  const doc = { getElementById(id) { return elements[id] ||= element(); } };
  doc.getElementById('governance-link').hidden = true;
  doc.getElementById('success').hidden = true;
  const fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => url.endsWith('/login')
      ? { must_change_password: true } : { must_change_password: false } };
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'public', 'first-login.js'), 'utf8'), { document: doc, fetch, JSON, Error });
  doc.getElementById('employee-code').value = 'EMP1';
  doc.getElementById('password').value = 'temporary';
  await doc.getElementById('login-form').fire('submit');
  assert.equal(doc.getElementById('change-form').hidden, false);
  doc.getElementById('current-password').value = 'temporary';
  doc.getElementById('new-password').value = 'a-long-new-password';
  doc.getElementById('confirm-password').value = 'different-password';
  await doc.getElementById('change-form').fire('submit');
  assert.equal(calls.some(call => call.url.endsWith('/change-password')), false);
  doc.getElementById('confirm-password').value = 'a-long-new-password';
  await doc.getElementById('change-form').fire('submit');
  assert.deepEqual(calls.map(call => call.url), ['/api/auth/login', '/api/auth/change-password', '/api/auth/logout']);
  assert.equal(JSON.parse(calls[1].options.body).current_password, 'temporary');
  assert.equal(doc.getElementById('success').hidden, false);
  assert.equal(doc.getElementById('governance-link').hidden, false);
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
      { interaction_id: 'new', employee_id: 'EMP', person_name: 'Pessoa nova', department_name: 'Financeiro',
        department_code: 'FIN', platform: 'chatgpt_web', status: 'complete', received_at: '2026-11-19T15:00:00Z' }], total: 1 },
    '/api/governance/investigations': { investigations: [] },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
  });
  p.el('department-code').value = 'OLD';
  const pending = p.el('search-form').fire('submit');
  p.el('department-code').value = 'NEW';
  await p.el('search-form').fire('submit');
  resolveOld({ items: [{ interaction_id: 'old', employee_id: 'EMP' }], total: 1 });
  await pending;
  const rendered = p.el('interactions').children[0].children.map(cell => cell.textContent);
  assert.deepEqual(rendered, ['Pessoa nova', 'Financeiro', 'chatgpt_web', 'complete', '19/11/2026, 12:00']);
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

test('access request grants scoped use without a second approver', async () => {
  let created = false;
  const access = { id: 'case-2', purpose: 'Suspeita documentada de vazamento', status: 'approved',
    requested_by: 'GOV1', viewers: ['GOV1'], can_approve: false, can_reject: false, can_use: true,
    target_employee_code: 'EMP1', expires_at: '2099-01-01T00:00:00Z' };
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [{
      interaction_id: '00000000-0000-0000-0000-000000000002', employee_id: 'EMP1',
    }], total: 1 },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
    '/api/governance/investigations': options => {
      if (options.method === 'POST') { created = true; return access; }
      return { investigations: created ? [access] : [] };
    },
    '/api/capture/v1/interactions/00000000-0000-0000-0000-000000000002?investigation_id=case-2': {
      prompt: { text: 'synthetic prompt' }, responses: [{ text: 'synthetic response' }],
    },
  });
  p.el('investigation-employee-code').value = 'EMP1';
  await p.el('investigation-form').fire('submit');
  const request = p.calls.find(call => call.url === '/api/governance/investigations' && call.options.method === 'POST');
  assert.deepEqual(JSON.parse(request.options.body), {
    employee_code: 'EMP1',
  });
  assert.match(p.el('active-case').textContent, /acesso registrado para EMP1 até 2099/i);
  assert.deepEqual(p.el('investigations').children[0].children
    .filter(child => child.type === 'button').map(button => button.textContent), ['Usar acesso']);
  await p.el('investigations').children[0].children.at(-1).fire('click');
  await p.el('interactions').children[0].children.at(-1).fire('click');
  assert.equal(p.el('detail').children[0].textContent, 'synthetic prompt');
  assert.equal(p.calls.some(call => call.url.includes('/decision/')), false);
});

test('legacy pending investigation has no decision or content action', async () => {
  const p = await portal({
    '/api/auth/me': { role: 'governance', must_change_password: false },
    '/api/capture/v1/admin/analytics/summary': { totals: { interactions: 0, responses: 0 } },
    '/api/capture/v1/admin/analytics/departments': { departments: [] },
    '/api/capture/v1/admin/analytics/interactions': { items: [], total: 0 },
    '/api/capture/v1/admin/machines/assignment-requests': { items: [] },
    '/api/governance/investigations': { investigations: [{ id: 'case-legacy', purpose: 'Legacy case',
      status: 'pending', viewers: ['GOV1'], requested_by: 'GOV2', target_employee_code: null,
      can_approve: false, can_reject: false, can_use: false }] },
  });
  const buttons = p.el('investigations').children[0].children.filter(child => child.type === 'button');
  assert.deepEqual(buttons.map(child => child.textContent), []);
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
