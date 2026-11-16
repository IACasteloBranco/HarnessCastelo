const $ = id => document.getElementById(id);
let currentConfig;
async function send(message) {
  const result = await chrome.runtime.sendMessage(message);
  if (!result?.ok) throw new Error(result?.error || 'Sem resposta da extensão.');
  return result.data;
}
async function refresh() {
  const config = await send({type: 'status'});
  currentConfig = config;
  $('enabled').checked = config.enabled;
  $('enabled').disabled = !config.privacyNotice.accepted && !config.enabled;
  $('capture-readiness').textContent = config.enabled && !config.captureAllowed
    ? 'Ativação salva, mas a captura está pausada até sessão, aviso e vínculo estarem válidos. Pode retomar quando forem restabelecidos; desmarque e salve para desligá-la.'
    : config.captureAllowed ? 'Pronta para capturar; cada envio ainda depende da disponibilidade da API.' : 'Captura desativada.';
  $('privacy-notice').hidden = config.privacyNotice.accepted;
  $('privacy-version').textContent = config.privacyNotice.version;
  $('privacy-ack').disabled = config.privacyNotice.accepted;
  $('privacy-ack-label').hidden = config.privacyNotice.accepted;
  $('accept-privacy').hidden = config.privacyNotice.accepted;
  $('accept-privacy').disabled = !$('privacy-ack').checked || !config.employeeCode;
  $('privacy-accepted').hidden = !config.privacyNotice.accepted;
  $('privacy-accepted').textContent = config.privacyNotice.accepted
    ? `Ciência registrada em ${new Date(config.privacyNotice.acceptedAt).toLocaleString('pt-BR')}. A captura continua sob seu controle.` : '';
  $('cloud-login').hidden = !config.cloud;
  $('login-fields').hidden = config.authenticated;
  $('login').disabled = !config.configured || config.authenticated;
  $('logout').disabled = !config.authenticated;
  $('account').textContent = config.employeeCode
    ? `Sessão Harness: ${config.employeeCode}. Expira em ${new Date(config.expiresAt * 1000).toLocaleString('pt-BR')}.`
    : config.authProblem || (config.configured ? 'Entre com seu código e senha do Harness.' : 'URL do servidor Harness inválida.');
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id) { $('probe-status').textContent = 'Nenhuma aba ativa.'; return; }
  try {
    const probe = await chrome.tabs.sendMessage(tab.id, {type: 'probe_status'});
    $('probe-status').textContent = probe?.active
      ? `Sonda ativa (adapter ${probe.adapterVersion}).` : 'Sonda não respondeu.';
  } catch {
    $('probe-status').textContent = 'Extensão não carregada nesta aba. Recarregue a aba do ChatGPT ou Claude após atualizar a extensão.';
  }
}
$('config').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await send({type: 'save', enabled: $('enabled').checked});
    $('status').textContent = 'Configuração salva. Recarregue a aba do ChatGPT ou Claude.';
    await refresh();
  } catch (error) {
    $('status').textContent = error.message;
    await refresh().catch(() => {});
  }
});
$('privacy-ack').addEventListener('change', () => {
  $('accept-privacy').disabled = !$('privacy-ack').checked || !currentConfig?.employeeCode;
});
$('accept-privacy').addEventListener('click', async () => {
  try {
    if (!$('privacy-ack').checked) throw new Error('Marque a confirmação depois de ler o aviso.');
    await send({type: 'accept_privacy_notice', version: currentConfig.privacyNotice.version});
    $('status').textContent = 'Ciência registrada. Captura ativada para a conta autenticada.';
    await refresh();
  } catch (error) { $('status').textContent = error.message; }
});
$('delete-local-data').addEventListener('click', async () => {
  if (!window.confirm('Apagar os dados locais desta instalação e gerar um novo identificador? Os dados no backend não serão apagados.')) return;
  try {
    await send({type: 'delete_local_data'});
    $('status').textContent = 'Dados locais removidos. Entre no Harness e solicite ao responsável a exclusão dos dados no backend.';
    await refresh();
  } catch (error) { $('status').textContent = error.message; }
});
$('login').addEventListener('click', async () => {
  try {
    if (!currentConfig?.configured) throw new Error('URL do servidor Harness inválida.');
    const login = await send({type: 'login', employeeCode: $('employee-code').value.trim(), password: $('password').value});
    if (login.must_change_password) {
      await chrome.tabs.create({url: login.password_change_url});
      $('status').textContent = 'Troque sua senha temporária na página da Governança e depois entre novamente na extensão.';
      return;
    }
    $('status').textContent = 'Sessão iniciada. A instalação foi vinculada automaticamente à sua conta.';
    await refresh();
  } catch (error) {
    $('status').textContent = error.message;
    await refresh().catch(() => {});
  }
  finally { $('password').value = ''; }
});
$('logout').addEventListener('click', async () => {
  try { await send({type: 'logout'}); await refresh(); }
  catch (error) { $('status').textContent = error.message; }
});
$('health').addEventListener('click', async () => {
  try { await send({type: 'health'}); $('status').textContent = 'API Harness disponível.'; }
  catch (error) { $('status').textContent = error.message; }
});
refresh().catch(error => { $('status').textContent = error.message; });
