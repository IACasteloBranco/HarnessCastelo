"use strict";
const $ = id => document.getElementById(id);
const requestedTv = location.pathname === '/tv';
const show = screen => {
  for (const id of ['login', 'change', 'portal', 'tv']) $(`${id}-screen`).hidden = id !== screen;
  document.body.classList.toggle('tv-mode', screen === 'tv');
  const path = screen === 'change' ? '/change-password' : screen === 'tv' ? '/tv' : '/';
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
let detailVersion = 0;
let interactionVersion = 0;
let analyticsVersion = 0;
let tvRefreshTimer = null;
let tvHasData = false;
function clearDetail() { detailVersion++; $('detail').replaceChildren(); }
function rows(id, items, fields) {
  const target = $(id);
  target.replaceChildren();
  for (const item of items) {
    const row = document.createElement('li');
    for (const field of fields) {
      const cell = document.createElement('span');
      cell.textContent = String(item[field] ?? '');
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
    for (const [label, value] of [['Código', item.department_code], ['Plataforma', item.platform],
      ['Interações', item.interactions], ['Respostas', item.responses]]) {
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
    for (const content of [result.prompt?.text, ...(result.responses || []).map(response => response.text)]) {
      const paragraph = document.createElement('p');
      paragraph.textContent = String(content ?? '');
      $('detail').append(paragraph);
    }
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
          await interactions();
        });
        row.append(button);
      }
      target.append(row);
    }
  } catch (error) { errorMessage(error); }
}
async function machines() {
  try {
    const result = await api('/api/capture/v1/admin/machines/assignment-requests');
    if ($('portal-screen').hidden) return;
    const target = $('machines');
    target.replaceChildren();
    for (const item of result.items) {
      const row = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = `${item.installation_id} · ${item.requested_employee_id} · ${item.person_name || 'Não atribuído'} · ${item.department_code || ''}`;
      row.append(label);
      for (const action of ['approve', 'reject']) {
        if (action === 'approve' && !item.can_approve) continue;
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = action === 'approve' ? 'Aprovar' : 'Rejeitar';
        button.addEventListener('click', async () => {
          try {
            await api(`/api/capture/v1/admin/machines/${encodeURIComponent(item.installation_id)}/assignment-request/${action}`, { method: 'POST' });
            await machines();
          } catch (error) { errorMessage(error); }
        });
        row.append(button);
      }
      target.append(row);
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
  const params = todayParams().toString();
  const query = `?${params}`;
  try {
    const summary = await api(`/api/capture/v1/admin/analytics/tv${query}`);
    const totals = summary.totals;
    const departments = (summary.by_department || []).filter(item => item.interactions > 0);
    const platformRows = (summary.by_platform || []).map(item => ({
      label: item.platform === 'chatgpt_web' ? 'ChatGPT Web' : item.platform === 'claude_web' ? 'Claude Web' : 'Outra plataforma',
      interactions: item.interactions,
    }));

    $('tv-interactions').textContent = new Intl.NumberFormat('pt-BR').format(totals.interactions);
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
    $('tv-error').textContent = tvHasData
      ? 'Não foi possível atualizar. Os indicadores exibidos são da última consulta.'
      : 'Não foi possível carregar os dados da extensão. Confira a conexão e tente novamente.';
  }
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
    rows('interactions', result.items, ['interaction_id', 'employee_id', 'department_code', 'platform', 'status', 'received_at']);
    $('interaction-count').textContent = `${result.total} interações`;
  } catch (error) { errorMessage(error); }
}
async function session() {
  try {
    const me = await api('/api/auth/me');
    if (me.must_change_password) show('change');
    else if (me.role === 'governance') {
      if (requestedTv || location.pathname === '/tv') {
        show('tv');
        await tvDashboard();
        clearInterval(tvRefreshTimer);
        tvRefreshTimer = setInterval(() => { if (!document.hidden && location.pathname === '/tv') void tvDashboard(); }, 60_000);
      } else {
        show('portal');
        await analytics();
        await investigations();
        await machines();
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
    if (result.must_change_password) show('change');
    else await session();
  } catch (error) { errorMessage(error); }
});
$('search-form').addEventListener('submit', async event => {
  event.preventDefault();
  clearDetail();
  await analytics();
});
$('investigation-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    activeCase = await api('/api/governance/investigations', { method: 'POST', body: JSON.stringify({
      purpose: $('purpose').value.trim(),
      employee_code: $('investigation-employee-code').value.trim(),
    }) });
    clearDetail();
    $('active-case').textContent = `Acesso registrado para ${activeCase.target_employee_code} até ${activeCase.expires_at}.`;
    $('investigation-form').reset();
    await investigations();
    await interactions();
  } catch (error) { errorMessage(error); }
});
$('change-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({
      current_password: $('current-password').value,
      new_password: $('new-password').value,
    }) });
    $('current-password').value = '';
    $('new-password').value = '';
    await session();
  } catch (error) { errorMessage(error); }
});
$('logout').addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', { method: 'POST' });
    activeCase = null;
    interactionVersion++;
    analyticsVersion++;
    clearDetail();
    for (const id of ['summary', 'interaction-count', 'active-case', 'message']) $(id).textContent = '';
    for (const id of ['departments', 'interactions', 'investigations', 'machines']) $(id).replaceChildren();
    show('login');
  } catch (error) { errorMessage(error); }
});
$('tv-fullscreen').addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { $('tv-error').textContent = 'O navegador não permitiu ativar a tela cheia.'; }
});
void session();
