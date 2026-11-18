'use strict';
const $ = id => document.getElementById(id);
async function api(path, body) {
  const response = await fetch(path, { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) throw Error(result?.detail || 'Não foi possível concluir. Confira os dados e tente novamente.');
  return result;
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const result = await api('/api/auth/login', {
      employee_code: $('employee-code').value.trim(), password: $('password').value,
    });
    $('password').value = '';
    if (result.must_change_password) {
      $('current-password').value = '';
      $('change-form').hidden = false;
      $('login-form').hidden = true;
      $('message').textContent = 'Defina uma nova senha com pelo menos 12 caracteres.';
    } else {
      await api('/api/auth/logout', {});
      $('success').textContent = 'Esta conta já está com a senha atualizada. Acesse a Governança e entre novamente.';
      $('success').hidden = false;
      $('governance-link').hidden = false;
      $('message').textContent = '';
    }
  } catch (error) { $('message').textContent = error.message; }
});
$('change-form').addEventListener('submit', async event => {
  event.preventDefault();
  if ($('new-password').value !== $('confirm-password').value) {
    $('message').textContent = 'As senhas informadas não coincidem.';
    return;
  }
  try {
    await api('/api/auth/change-password', {
      current_password: $('current-password').value, new_password: $('new-password').value,
    });
    await api('/api/auth/logout', {});
    $('change-form').hidden = true;
    $('success').hidden = false;
    $('governance-link').hidden = false;
    $('message').textContent = '';
  } catch (error) { $('message').textContent = error.message; }
});
