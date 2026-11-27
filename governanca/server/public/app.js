"use strict";
const $ = id => document.getElementById(id);
const markdown = typeof markdownit === 'function'
  ? markdownit({ html: false, linkify: true, breaks: true }).disable('image') : null;
function contentBlock(label, text) {
  const block = document.createElement('div');
  block.className = 'interaction-message markdown-content';
  block.dataset.label = label;
  block.setAttribute('role', 'group');
  block.setAttribute('aria-label', label);
  const content = String(text || 'Sem texto capturado');
  if (markdown) block.innerHTML = markdown.render(content);
  else block.textContent = content;
  return block;
}
const requestedTv = location.pathname === '/tv';
const show = screen => {
  for (const id of ['login', 'portal', 'tv']) $(`${id}-screen`).hidden = id !== screen;
  document.body.classList.toggle('tv-mode', screen === 'tv');
  const path = screen === 'tv' ? '/tv' : '/';
  if (location.pathname !== path) history.replaceState(null, '', path);
};
async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json' } : undefined,
  });
  if (!response.ok) throw Error((await response.json()).detail || 'Falha na solicitação.');
  return response.status === 204 ? null : response.json();
}
function errorMessage(error) { $('message').textContent = error.message; }
let activeCase = null;
let temporaryPassword = '';
let accountOperationVersion = 0;
let detailVersion = 0;
let interactionVersion = 0;
let analyticsVersion = 0;
let activityVersion = 0;
let machineHealthVersion = 0;
let heartbeatSettingsVersion = 0;
let backupStatusVersion = 0;
let policyCatalogVersion = 0;
let activePolicyVersion = 0;
let tvRefreshTimer = null;
let tvHasData = false;
let tvInteractionVersion = 0;
function clearDetail() { detailVersion++; $('detail').replaceChildren(); }
for (const [id, page] of [['nav-overview', 'overview'], ['nav-health', 'health'], ['nav-policies', 'policies']]) {
  $(id).addEventListener('click', () => {
    for (const target of ['overview', 'health', 'policies']) {
      $(`page-${target}`).hidden = target !== page;
      const tab = $(`nav-${target}`);
      if (target === page) tab.setAttribute('aria-current', 'page');
      else tab.removeAttribute('aria-current');
    }
    if (page === 'health') { void activityAnalytics(); void machineHealth(); void heartbeatSettings(); void backupStatus(); }
    if (page === 'policies') void policyCatalog();
  });
}
function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value ?? '') : new Intl.DateTimeFormat('pt-BR', {
    timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short',
  }).format(date);
}
function rows(id, items, fields) {
  const target = $(id);
  target.replaceChildren();
  for (const item of items) {
    const row = document.createElement('li');
    for (const [field, label] of fields) {
      const cell = document.createElement('span');
      cell.textContent = field === 'received_at' ? formatDate(item[field]) : String(item[field] ?? '');
      cell.dataset.label = label;
      row.append(cell);
    }
    if (id === 'interactions' && activeCase && activeCase.target_employee_code === item.employee_id) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Ver detalhe';
      button.addEventListener('click', () => detail(item.interaction_id));
      row.append(button);
    }
    target.append(row);
  }
}
function departmentRows(items) {
  const target = $('departments');
  target.replaceChildren();
  for (const item of items) {
    const row = document.createElement('li');
    const title = document.createElement('strong');
    title.textContent = String(item.department_name ?? item.department_code ?? '');
    const facts = document.createElement('dl');
    for (const [label, value] of [['Plataforma', item.platform], ['Interações', item.interactions],
      ['Respostas', item.responses]]) {
      const group = document.createElement('div');
      const term = document.createElement('dt');
      term.textContent = label;
      const detail = document.createElement('dd');
      detail.textContent = String(value ?? '');
      group.append(term, detail);
      facts.append(group);
    }
    row.append(title, facts);
    target.append(row);
  }
}
async function detail(interactionId) {
  clearDetail();
  const version = detailVersion;
  const investigationId = activeCase?.id;
  if (!investigationId) return;
  try {
    const result = await api(`/api/capture/v1/interactions/${encodeURIComponent(interactionId)}?investigation_id=${encodeURIComponent(investigationId)}`);
    if (version !== detailVersion || activeCase?.id !== investigationId || $('portal-screen').hidden) return;
    $('detail').append(contentBlock('Prompt', result.prompt?.text),
      ...(result.responses || []).map((response, index) => contentBlock(`Resposta ${index + 1}`, response.text)));
  } catch (error) { errorMessage(error); }
}
async function investigations() {
  try {
    const result = await api('/api/governance/investigations');
    if ($('portal-screen').hidden) return;
    const target = $('investigations');
    target.replaceChildren();
    const cases = result.investigations || [];
    if (!cases.some(item => item.id === activeCase?.id && item.can_use && item.target_employee_code &&
      Date.parse(item.expires_at) > Date.now())) {
      activeCase = null;
      clearDetail();
      $('active-case').textContent = 'Nenhuma investigação ativa.';
    }
    $('export-interactions').hidden = !activeCase?.can_use || !activeCase.target_employee_code ||
      Date.parse(activeCase.expires_at) <= Date.now();
    for (const item of cases) {
      const row = document.createElement('li');
      const description = document.createElement('span');
      description.textContent = `${item.purpose} · ${item.status} · colaborador ${item.target_employee_code || 'não definido'} · solicitante ${item.requested_by} · expira ${item.expires_at || '—'}`;
      row.append(description);
      if (item.can_use && item.target_employee_code && Date.parse(item.expires_at) > Date.now()) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Usar acesso';
        button.addEventListener('click', async () => {
          activeCase = item;
          clearDetail();
          $('active-case').textContent = `Acesso ativo para ${item.target_employee_code} até ${item.expires_at}.`;
          $('export-interactions').hidden = false;
          await interactions();
        });
        row.append(button);
      }
      target.append(row);
    }
  } catch (error) { errorMessage(error); }
}
async function accountDepartments() {
  try {
    const result = await api('/api/auth/governance/departments');
    for (const [id, firstLabel] of [['account-department', 'Selecione um departamento'],
      ['department-code', 'Todos']]) {
      const select = $(id);
      select.replaceChildren();
      const first = document.createElement('option');
      first.value = '';
      first.textContent = firstLabel;
      select.append(first);
      for (const department of result.departments) {
        const option = document.createElement('option');
        option.value = department.code;
        option.textContent = department.name;
        select.append(option);
      }
    }
  } catch (error) { errorMessage(error); }
}
function periodParams() {
  const params = new URLSearchParams();
  for (const [id, key] of [['from-date', 'from'], ['to-date', 'to']]) {
    if ($(id).value) params.set(key, new Date(`${$(id).value}Z`).toISOString());
  }
  if (params.has('from') && params.has('to') && params.get('from') >= params.get('to')) {
    throw Error('O início deve ser anterior ao fim.');
  }
  return params;
}
async function analytics() {
  const version = ++analyticsVersion;
  try {
    const params = periodParams();
    const period = params.size ? `?${params}` : '';
    const [summary, departments] = await Promise.all([
      api(`/api/capture/v1/admin/analytics/summary${period}`),
      api(`/api/capture/v1/admin/analytics/departments${period}`),
    ]);
    if (version !== analyticsVersion || $('portal-screen').hidden) return;
    $('summary').textContent = `Interações: ${summary.totals.interactions} · Respostas: ${summary.totals.responses}`;
    departmentRows(departments.departments);
    await interactions();
  } catch (error) { errorMessage(error); }
}
async function activityAnalytics() {
  const version = ++activityVersion;
  try {
    const summary = await api(`/api/capture/v1/admin/analytics/summary?${todayParams()}`);
    if (version !== activityVersion || $('portal-screen').hidden) return;
    const totals = summary.totals;
    $('activity-interactions').textContent = new Intl.NumberFormat('pt-BR').format(totals.interactions);
    $('activity-complete').textContent = new Intl.NumberFormat('pt-BR').format(totals.complete_responses);
    $('activity-incomplete').textContent = new Intl.NumberFormat('pt-BR').format(totals.incomplete_responses);
    const lastActivity = (summary.by_department || []).map(item => item.last_activity_at)
      .filter(Boolean).sort().at(-1);
    $('activity-last-event').textContent = lastActivity
      ? `Última atividade registrada hoje: ${formatDate(lastActivity)}.`
      : 'Nenhuma atividade de captura registrada hoje.';
    $('activity-updated').textContent = `Atualizado às ${new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit',
    }).format(new Date())}`;
  } catch {
    if (version !== activityVersion || $('portal-screen').hidden) return;
    $('activity-updated').textContent = 'Indisponível';
    $('activity-last-event').textContent = 'Não foi possível consultar a atividade de captura.';
  }
}
async function machineHealth() {
  const version = ++machineHealthVersion;
  try {
    const result = await api('/api/capture/v1/admin/machines/health');
    if (version !== machineHealthVersion || $('portal-screen').hidden) return;
    const items = result.items || [];
    const staleHours = Number(result.heartbeat?.heartbeat_stale_hours) || 72;
    const cutoff = Date.now() - staleHours * 60 * 60 * 1000;
    const counts = {healthy: 0, stale: 0, paused: 0, revoked: 0, unknown: 0};
    const rows = $('installation-health-rows');
    rows.replaceChildren();
    for (const item of items) {
      const seenAt = Date.parse(item.last_seen_at || '');
      const recent = Number.isFinite(seenAt) && seenAt <= Date.now() + 5 * 60_000 && seenAt >= cutoff;
      const captureEnabled = item.capture_enabled === null ? null : Number(item.capture_enabled) === 1;
      const state = item.revoked_at ? 'revoked' : !recent ? 'stale'
        : captureEnabled === false ? 'paused' : captureEnabled === true ? 'healthy' : 'unknown';
      counts[state]++;
      const label = ({revoked: 'Revogada', stale: 'Sem sinal recente', paused: 'Captura pausada',
        healthy: 'Saudável', unknown: 'Sinal recente'})[state];
      const row = document.createElement('tr');
      for (const value of [item.person_name || 'Não identificado', item.department_name || 'Sem departamento',
        `…${String(item.installation_id || '').slice(-8)}`, item.extension_version || 'Não reportada',
        captureEnabled === null ? 'Não reportado' : captureEnabled ? 'Ativa' : 'Pausada',
        item.last_seen_at ? formatDate(item.last_seen_at) : 'Nunca']) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      }
      const statusCell = document.createElement('td');
      const status = document.createElement('span');
      status.className = `status-pill ${state === 'healthy' ? 'status-ok' : 'status-warn'}`;
      status.textContent = label;
      statusCell.append(status);
      row.append(statusCell);
      rows.append(row);
    }
    $('installation-count').textContent = new Intl.NumberFormat('pt-BR').format(items.length);
    $('installation-healthy').textContent = new Intl.NumberFormat('pt-BR').format(counts.healthy);
    $('installation-stale').textContent = new Intl.NumberFormat('pt-BR').format(counts.stale);
    $('installation-paused').textContent = new Intl.NumberFormat('pt-BR').format(counts.paused);
    $('installation-revoked').textContent = new Intl.NumberFormat('pt-BR').format(counts.revoked);
    $('installation-unknown').textContent = new Intl.NumberFormat('pt-BR').format(counts.unknown);
    $('installation-health-empty').hidden = items.length > 0;
    $('installation-health-updated').textContent = `Atualizado às ${new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit',
    }).format(new Date())}`;
  } catch {
    if (version === machineHealthVersion && !$('portal-screen').hidden)
      $('installation-health-updated').textContent = 'Consulta indisponível';
  }
}
async function heartbeatSettings() {
  const version = ++heartbeatSettingsVersion;
  try {
    const result = await api('/api/auth/governance/heartbeat-settings');
    if (version !== heartbeatSettingsVersion || $('portal-screen').hidden) return;
    $('heartbeat-interval-hours').value = result.interval_hours;
    $('heartbeat-stale-hours').value = result.stale_after_hours;
  } catch {
    if (version === heartbeatSettingsVersion && !$('portal-screen').hidden)
      $('heartbeat-settings-status').textContent = 'Não foi possível carregar a configuração.';
  }
}
async function saveHeartbeatSettings(event) {
  event.preventDefault();
  const intervalHours = Number($('heartbeat-interval-hours').value);
  const staleAfterHours = Number($('heartbeat-stale-hours').value);
  if (staleAfterHours < intervalHours * 2) {
    $('heartbeat-settings-status').textContent = 'A tolerância deve ser pelo menos o dobro do intervalo.';
    return;
  }
  try {
    await api('/api/auth/governance/heartbeat-settings', {method: 'PUT', body: JSON.stringify({
      interval_hours: intervalHours, stale_after_hours: staleAfterHours,
    })});
    $('heartbeat-settings-status').textContent = 'Configuração salva. O novo intervalo será aplicado no próximo heartbeat.';
    void machineHealth();
  } catch (error) {
    $('heartbeat-settings-status').textContent = error.message;
  }
}
async function backupStatus(tv = false) {
  const version = ++backupStatusVersion;
  const statusId = tv ? 'tv-backup-status' : 'backup-status';
  try {
    const result = await api('/api/auth/governance/backup-status');
    if (version !== backupStatusVersion || (tv ? $('tv-screen').hidden : $('portal-screen').hidden)) return;
    const label = result.state === 'fresh' ? (tv ? 'Recente' : 'Último sucesso dentro de 97 horas')
      : result.state === 'stale' ? 'Atrasado' : 'Sem dado operacional';
    $(statusId).textContent = label;
    $(statusId).className = `status-pill ${result.state === 'fresh' ? 'status-ok' : 'status-warn'}`;
    const lastSuccess = result.last_success_at ? formatDate(result.last_success_at) : 'Sem registro disponível';
    if (tv) $('tv-backup-status').textContent = `${label} · ${lastSuccess}`;
    else $('backup-last-success').textContent = lastSuccess;
  } catch {
    if (version !== backupStatusVersion) return;
    $(statusId).textContent = 'Consulta indisponível';
    if (!tv) $('backup-last-success').textContent = 'Não foi possível consultar o serviço.';
  }
}
async function policyCatalog(tv = false) {
  const version = ++policyCatalogVersion;
  try {
    const result = await api('/api/auth/governance/policies');
    if (version !== policyCatalogVersion || (tv ? $('tv-screen').hidden : $('portal-screen').hidden)) return;
    if (tv) {
      $('tv-policy-version').textContent = `política v${result.extension.policy_version ?? 0} · servidor ${result.server_inspection.version}`;
      return;
    }
    const extension = result.extension;
    extension.configured_actions ||= {};
    activePolicyVersion = extension.policy_version ?? 0;
    $('extension-policy-version').textContent = `Política v${activePolicyVersion} · motor ${extension.version}`;
    $('policy-scope').textContent = `Regras R01–R09 e limite de análise. O motor registra decisões somente nesta instalação da extensão; o backend não recebe contagens.`;
    const actionDescription = {ALLOW: 'permite o envio', WARN: 'avisa e permite continuar',
      REVIEW: 'interrompe o envio para revisão local', BLOCK: 'impede o envio'};
    $('policy-action-summary').textContent = extension.actions.map(action => actionDescription[action] || action).join(' · ');
    $('policy-warning-scope').textContent = `Destino atual: ${extension.destination}. Os avisos de ${extension.warning_rules.join(' e ')} só se aplicam a destinos aprovados e não estão ativos neste fluxo.`;
    const rules = $('policy-rules');
    rules.replaceChildren();
    for (const item of extension.rules) {
      const row = document.createElement('li');
      const configured = extension.configured_actions[item.id];
      row.textContent = `${item.id} · ${item.label}: ${configured || item.effect}`;
      rules.append(row);
    }
    const controls = $('policy-controls');
    controls.replaceChildren();
    for (const item of extension.rules.filter(rule => rule.id !== 'LIMIT')) {
      const row = document.createElement('li');
      const label = document.createElement('label');
      label.textContent = `${item.id} · ${item.label}`;
      const select = document.createElement('select');
      select.dataset.rule = item.id;
      for (const [value, text] of [['', 'Padrão do motor'], ...extension.actions.map(action => [action, actionDescription[action] || action])]) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.selected = (extension.configured_actions[item.id] || '') === value;
        select.append(option);
      }
      label.append(select);
      row.append(label);
      controls.append(row);
    }
    const remote = result.server_inspection;
    $('server-policy-version').textContent = `Inspeção DLP · política v${remote.policy_version} · motor ${remote.version}`;
    const categories = $('server-policy-controls');
    categories.replaceChildren();
    for (const item of remote.categories) {
      const row = document.createElement('li');
      const label = document.createElement('label');
      label.textContent = item.name;
      const select = document.createElement('select');
      select.dataset.category = item.name;
      for (const [value, text] of [['allow', 'Permitir sem mascarar'], ['mask', 'Mascarar'], ['block', 'Bloquear']]) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.selected = item.action === value;
        select.append(option);
      }
      select.value = item.action;
      label.append(select);
      row.append(label);
      categories.append(row);
    }
  } catch {
    if (version !== policyCatalogVersion) return;
    if (tv) $('tv-policy-version').textContent = 'Indisponível';
    else $('extension-policy-version').textContent = 'Consulta indisponível';
  }
}
async function savePolicy(event) {
  event.preventDefault();
  const actions = Object.fromEntries([...$('policy-controls').querySelectorAll('select')]
    .map(select => [select.dataset.rule, select.value || null]));
  const serverActions = Object.fromEntries([...$('server-policy-controls').querySelectorAll('select')]
    .map(select => [select.dataset.category, select.value]));
  try {
    const saved = await api('/api/auth/governance/policies', {method: 'PUT', body: JSON.stringify({
      expected_version: activePolicyVersion, actions, server_actions: serverActions,
    })});
    activePolicyVersion = saved.version;
    $('policy-save-status').textContent = `Política v${saved.version} salva e auditada.`;
    await policyCatalog();
  } catch (error) {
    $('policy-save-status').textContent = error.message;
  }
}
function todayParams() {
  const timeZone = 'America/Sao_Paulo';
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  });
  const parts = date => Object.fromEntries(formatter.formatToParts(date).map(part => [part.type, part.value]));
  const current = parts(new Date());
  const today = Date.UTC(Number(current.year), Number(current.month) - 1, Number(current.day));
  const startOfSaoPauloDay = target => {
    let timestamp = target;
    for (let attempt = 0; attempt < 3; attempt++) {
      const local = parts(new Date(timestamp));
      const representedAsUtc = Date.UTC(Number(local.year), Number(local.month) - 1, Number(local.day),
        Number(local.hour), Number(local.minute), Number(local.second));
      timestamp += target - representedAsUtc;
    }
    return new Date(timestamp).toISOString();
  };
  const tomorrow = new Date(today);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  return new URLSearchParams({ from: startOfSaoPauloDay(today), to: startOfSaoPauloDay(tomorrow.getTime()) });
}
function appendTvBars(target, items, labelKey, valueKey) {
  target.replaceChildren();
  const max = Math.max(1, ...items.map(item => Number(item[valueKey]) || 0));
  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'tv-bar-row';
    const label = document.createElement('span');
    label.className = 'tv-bar-label';
    label.textContent = String(item[labelKey] || 'Não identificado');
    const track = document.createElement('div');
    track.className = 'tv-bar-track';
    const fill = document.createElement('div');
    fill.className = 'tv-bar-fill';
    fill.style.width = `${Math.max(0, (Number(item[valueKey]) || 0) / max * 100)}%`;
    track.append(fill);
    const value = document.createElement('strong');
    value.textContent = new Intl.NumberFormat('pt-BR').format(Number(item[valueKey]) || 0);
    row.append(label, track, value);
    target.append(row);
  }
}
async function tvDashboard() {
  const departmentFilter = $('tv-department');
  const params = todayParams();
  const departmentCode = departmentFilter.value;
  if (departmentCode) params.set('department_code', departmentCode);
  const query = `?${params}`;
  try {
    const summary = await api(`/api/capture/v1/admin/analytics/tv${query}`);
    if (!departmentFilter.dataset.loaded) {
      for (const item of summary.by_department || []) {
        const option = document.createElement('option');
        option.value = item.department_code;
        option.textContent = item.department_name;
        departmentFilter.append(option);
      }
      departmentFilter.dataset.loaded = 'true';
    }
    await tvInteractions(departmentCode);
    const totals = summary.totals;
    const departments = (summary.by_department || []).filter(item => item.interactions > 0);
    const platformRows = (summary.by_platform || []).map(item => ({
      label: item.platform === 'chatgpt_web' ? 'ChatGPT Web' : item.platform === 'claude_web' ? 'Claude Web' : 'Outra plataforma',
      interactions: item.interactions,
    }));

    $('tv-interactions').textContent = new Intl.NumberFormat('pt-BR').format(totals.interactions);
    $('tv-complete').textContent = new Intl.NumberFormat('pt-BR').format(totals.complete_responses);
    $('tv-employees').textContent = new Intl.NumberFormat('pt-BR').format(totals.employees);
    $('tv-departments-count').textContent = new Intl.NumberFormat('pt-BR').format(totals.departments);
    $('tv-incomplete').textContent = new Intl.NumberFormat('pt-BR').format(totals.incomplete_responses);
    appendTvBars($('tv-departments'), departments.slice(0, 8), 'department_name', 'interactions');
    appendTvBars($('tv-platforms'), platformRows, 'label', 'interactions');
    $('tv-empty').hidden = totals.interactions > 0;
    $('tv-last-event').textContent = totals.last_activity_at
      ? `Último evento: ${new Intl.DateTimeFormat('pt-BR', {
        timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit',
      }).format(new Date(totals.last_activity_at))}`
      : 'Nenhum evento recebido hoje';
    $('tv-last-updated').textContent = `Consulta às ${new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).format(new Date())} · horário de Brasília`;
    $('tv-error').textContent = '';
    tvHasData = true;
  } catch (error) {
    $('tv-interactions-list').replaceChildren();
    $('tv-content-status').textContent = 'Não foi possível carregar o conteúdo das interações.';
    $('tv-error').textContent = tvHasData
      ? 'Não foi possível atualizar. Os indicadores exibidos são da última consulta.'
      : 'Não foi possível carregar os dados da extensão. Confira a conexão e tente novamente.';
  }
}
async function tvInteractions(departmentCode = '') {
  const query = departmentCode ? `?department_code=${encodeURIComponent(departmentCode)}` : '';
  const version = ++tvInteractionVersion;
  const result = await api(`/api/capture/v1/admin/analytics/tv-interactions${query}`);
  if (version !== tvInteractionVersion) return;
  const target = $('tv-interactions-list');
  target.replaceChildren();
  for (const item of result.items) {
    const card = document.createElement('article');
    card.className = 'tv-interaction';
    const heading = document.createElement('h4');
    heading.textContent = `${item.person_name} · ${item.department_name} · ${item.platform}`;
    card.append(heading, contentBlock('Prompt', item.prompt?.text));
    for (const [index, answer] of (item.responses || []).entries())
      card.append(contentBlock(`Resposta ${index + 1}`, answer.text));
    target.append(card);
  }
  $('tv-content-status').textContent = `${result.items.length} interações recebidas nos últimos 2 dias.`;
}
async function interactions() {
  const version = ++interactionVersion;
  try {
    const params = periodParams();
    for (const [input, key] of [['department-code', 'department_code'], ['employee-id', 'employee_id'],
      ['platform', 'platform']]) {
      if ($(input).value.trim()) params.set(key, $(input).value.trim());
    }
    const result = await api(`/api/capture/v1/admin/analytics/interactions${params.size ? `?${params}` : ''}`);
    if (version !== interactionVersion || $('portal-screen').hidden) return;
    rows('interactions', result.items, [['person_name', 'Pessoa'], ['department_name', 'Departamento'], ['platform', 'Plataforma'], ['status', 'Status'], ['received_at', 'Recebido']]);
    $('interaction-count').textContent = `${result.total} interações`;
  } catch (error) { errorMessage(error); }
}
async function session() {
  try {
    const me = await api('/api/auth/me');
    if (me.must_change_password) location.replace('https://primeiro-login.castelotecnologia.com.br/');
    else if (me.role === 'governance') {
      if (requestedTv || location.pathname === '/tv') {
        show('tv');
        await Promise.all([tvDashboard(), backupStatus(true), policyCatalog(true)]);
        clearInterval(tvRefreshTimer);
        tvRefreshTimer = setInterval(() => {
          if (!document.hidden && location.pathname === '/tv') {
            void tvDashboard(); void backupStatus(true); void policyCatalog(true);
          }
        }, 30 * 60_000);
      } else {
        show('portal');
        await analytics();
        await activityAnalytics();
        await investigations();
        await accountDepartments();
      }
    }
    else { show('login'); $('message').textContent = 'Acesso reservado à governança.'; }
  } catch (error) {
    show('login');
  }
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({
      employee_code: $('employee-code').value.trim(), password: $('password').value,
    }) });
    $('password').value = '';
    if (result.must_change_password) location.replace('https://primeiro-login.castelotecnologia.com.br/');
    else await session();
  } catch (error) { errorMessage(error); }
});
$('policy-form').addEventListener('submit', savePolicy);
$('heartbeat-settings-form').addEventListener('submit', saveHeartbeatSettings);
$('search-form').addEventListener('submit', async event => {
  event.preventDefault();
  clearDetail();
  await analytics();
});
$('investigation-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    activeCase = await api('/api/governance/investigations', { method: 'POST', body: JSON.stringify({
      employee_code: $('investigation-employee-code').value.trim(),
    }) });
    clearDetail();
    $('active-case').textContent = `Acesso registrado para ${activeCase.target_employee_code} até ${activeCase.expires_at}.`;
    $('export-interactions').hidden = false;
    $('investigation-form').reset();
    await investigations();
    await interactions();
  } catch (error) { errorMessage(error); }
});
$('export-interactions').addEventListener('click', async () => {
  if (!activeCase?.target_employee_code) return;
  const url = `/api/capture/v1/employees/${encodeURIComponent(activeCase.target_employee_code)}/export?investigation_id=${encodeURIComponent(activeCase.id)}`;
  try {
    const response = await fetch(url, {credentials: 'same-origin'});
    if (!response.ok) throw Error((await response.json()).detail || 'Falha na exportação.');
    const blob = await response.blob();
    const link = document.createElement('a');
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = `interacoes-${activeCase.target_employee_code}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  } catch (error) { errorMessage(error); }
});
$('account-form').addEventListener('submit', async event => {
  event.preventDefault();
  const version = ++accountOperationVersion;
  temporaryPassword = '';
  $('copy-temporary-password').hidden = true;
  $('account-result').textContent = '';
  try {
    const result = await api('/api/auth/governance/accounts', { method: 'POST', body: JSON.stringify({
      employee_code: $('account-code').value.trim(),
      display_name: $('account-name').value.trim(),
      department_code: $('account-department').value,
    }) });
    if (version !== accountOperationVersion || $('portal-screen').hidden) return;
    temporaryPassword = result.temporary_password;
    $('account-result').textContent = `Conta ${result.employee_code} criada. Senha temporária: ${temporaryPassword}. Ela será exibida apenas nesta sessão e deverá ser trocada no primeiro acesso.`;
    $('copy-temporary-password').hidden = false;
    $('account-form').reset();
  } catch (error) {
    if (version === accountOperationVersion) errorMessage(error);
  }
});
$('reset-account-form').addEventListener('submit', async event => {
  event.preventDefault();
  const version = ++accountOperationVersion;
  temporaryPassword = '';
  $('copy-temporary-password').hidden = true;
  $('account-result').textContent = '';
  const employeeCode = $('reset-account-code').value.trim();
  if (!employeeCode || !confirm(`Redefinir a senha de ${employeeCode}? As sessões existentes serão encerradas.`)) return;
  try {
    const result = await api('/api/auth/governance/accounts/reset-password', {
      method: 'POST', body: JSON.stringify({ employee_code: employeeCode }),
    });
    if (version !== accountOperationVersion || $('portal-screen').hidden) return;
    temporaryPassword = result.temporary_password;
    $('account-result').textContent = `Senha temporária de ${result.employee_code}: ${temporaryPassword}. A colaboradora deverá trocá-la no próximo acesso.`;
    $('copy-temporary-password').hidden = false;
    $('reset-account-form').reset();
  } catch (error) {
    if (version === accountOperationVersion) errorMessage(error);
  }
});
$('copy-temporary-password').addEventListener('click', async () => {
  if (!temporaryPassword) return;
  try {
    await navigator.clipboard.writeText(temporaryPassword);
    $('account-result').textContent = 'Senha temporária copiada. Ela será exigida no primeiro acesso.';
  } catch (error) { errorMessage(error); }
});

$('logout').addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', { method: 'POST' });
    accountOperationVersion++;
    activeCase = null;
    interactionVersion++;
    analyticsVersion++;
    activityVersion++;
    backupStatusVersion++;
    policyCatalogVersion++;
    clearDetail();
    for (const id of ['summary', 'interaction-count', 'active-case', 'message', 'activity-interactions',
      'activity-complete', 'activity-incomplete', 'activity-last-event', 'activity-updated']) $(id).textContent = '';
    machineHealthVersion++;
    heartbeatSettingsVersion++;
    $('installation-health-rows').replaceChildren();
    for (const id of ['installation-health-updated', 'installation-count', 'installation-healthy',
      'installation-stale', 'installation-paused', 'installation-revoked', 'installation-unknown']) $(id).textContent = '';
    $('heartbeat-interval-hours').value = '';
    $('heartbeat-stale-hours').value = '';
    $('heartbeat-settings-status').textContent = '';
    for (const id of ['departments', 'interactions', 'investigations']) $(id).replaceChildren();
    temporaryPassword = '';
    $('account-result').textContent = '';
    $('copy-temporary-password').hidden = true;
    for (const id of ['backup-status', 'backup-last-success', 'extension-policy-version', 'policy-scope',
      'policy-warning-scope', 'server-policy-version', 'tv-backup-status', 'tv-policy-version']) $(id).textContent = '';
    $('policy-rules').replaceChildren();
    $('server-policy-controls').replaceChildren();
    show('login');
  } catch (error) { errorMessage(error); }
});
$('tv-department').addEventListener('change', () => { void tvDashboard(); });
$('tv-fullscreen').addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { $('tv-error').textContent = 'O navegador não permitiu ativar a tela cheia.'; }
});
$('tv-logout').addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', {method: 'POST'});
    clearInterval(tvRefreshTimer);
    backupStatusVersion++;
    policyCatalogVersion++;
    $('tv-interactions-list').replaceChildren();
    $('tv-content-status').textContent = '';
    $('tv-backup-status').textContent = '';
    $('tv-policy-version').textContent = '';
    show('login');
  } catch (error) { errorMessage(error); }
});
void session();
