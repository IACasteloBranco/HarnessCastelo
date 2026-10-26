"use strict";

const views = Object.fromEntries(["loading", "login", "password", "home", "connect", "chat", "governance"].map(name => [name, document.getElementById(`${name}-view`)]));
const state = { screen: "loading", employee: null, credentials: [], projects: [], connection: null, chat: { runs: [], pending: null, preview: null, busy: false, before: null, conversationId: null, projectId: null, title: null, conversations: [], search: "", listBefore: null }, runDetailId: null };
let sessionVersion = 0;
let credentialsVersion = 0;
let chatVersion = 0;
const $ = id => document.getElementById(id);
const markdown = window.markdownit({ html: false, linkify: true, breaks: true });
let selectedFiles = [];
let audioBusy = false;
let audioRecorder = null;
let audioStream = null;
let recordingTimer = null;
let profileDirty = false;

function setChatUserMenu(open) {
  $("chat-user-menu").hidden = !open;
  $("chat-side-user").setAttribute("aria-expanded", String(open));
  $("chat-side-user").setAttribute("aria-label", `${open ? "Fechar" : "Abrir"} menu do perfil`);
}

function show(screen, focus = true) {
  const previous = state.screen;
  if (previous === "chat" && screen !== "chat") stopRecording(true);
  state.screen = screen;
  setChatUserMenu(false);
  document.querySelector(".shell").classList.toggle("login-shell", screen === "login");
  document.querySelector(".shell").classList.toggle("workspace-shell", screen === "chat" || screen === "governance");
  document.querySelector(".shell").classList.toggle("chat-shell", screen === "chat");
  for (const [name, view] of Object.entries(views)) view.hidden = name !== screen;
  $("workspace-nav").hidden = !state.employee || state.employee.must_change_password || screen === "login" || screen === "password";
  $("chat-nav").hidden = state.employee?.role !== "collaborator";
  $("accounts-nav").hidden = state.employee?.role !== "collaborator";
  $("governance-nav").hidden = !(state.employee?.role === "governance" || state.employee?.can_govern);
  $("chat-sidebar-governance").hidden = !state.employee?.can_govern;
  $("chat-menu-governance").hidden = !state.employee?.can_govern;
  for (const [name, id] of [["chat", "chat-nav"], ["home", "accounts-nav"], ["governance", "governance-nav"]]) $(id).setAttribute("aria-current", screen === name ? "page" : "false");
  $("session-actions").hidden = !state.employee;
  $("employee-label").textContent = state.employee?.employee_code || "";
  $("status").hidden = true;
  if (previous !== screen) window.scrollTo(0, 0);
  if (focus) views[screen].querySelector("h1")?.focus({ preventScroll: true });
}

function status(message, error = false) {
  const element = $("status");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.hidden = false;
}

function formError(id, message) {
  const element = $(id);
  element.textContent = message;
  element.hidden = !message;
}

function setBusy(form, busy) {
  form.querySelector("button[type=submit]").disabled = busy;
  form.setAttribute("aria-busy", String(busy));
}

function clearSession() {
  stopRecording(true);
  audioBusy = false;
  if ($("artifact-dialog").open) $("artifact-dialog").close();
  sessionVersion++;
  credentialsVersion++;
  chatVersion++;
  state.employee = null;
  state.credentials = [];
  state.projects = [];
  state.connection = null;
  state.chat = { runs: [], pending: null, preview: null, busy: false, before: null, conversationId: null, projectId: null, title: null, conversations: [], search: "", listBefore: null };
  state.runDetailId = null;
  $("run-detail-content").textContent = "";
  $("run-detail").hidden = true;
  $("chat-text").value = "";
  selectedFiles = [];
  $("chat-attachments").value = "";
  $("chat-add-menu").open = false;
  if ($("project-dialog").open) $("project-dialog").close();
  if ($("context-dialog").open) $("context-dialog").close();
  renderSelectedFiles();
  $("chat-credential").replaceChildren();
  document.querySelector(".credential-picker").hidden = true;
  $("chat-header-accounts").hidden = true;
  $("login-password").value = "";
  $("password-form").reset();
  $("callback-form").reset();
  show("login");
}

async function api(path, options = {}) {
  const version = sessionVersion;
  let response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new Error("Sem conexão com o servidor. Verifique sua rede e tente novamente.");
  }
  if (response.status === 401) {
    if (path === "/api/auth/login") throw new Error("Código ou senha incorretos. Confira os dados e tente novamente.");
    if (version === sessionVersion) clearSession();
    throw new Error("Sua sessão terminou. Entre novamente para continuar.");
  }
  if (!response.ok) {
    if (response.status === 403) throw new Error("Esta ação não está disponível ou o pedido expirou. Confira seu acesso e tente novamente.");
    if (response.status === 429) throw new Error("Muitas tentativas. Aguarde um pouco antes de tentar novamente.");
    throw new Error(response.status >= 500 ? "O servidor está indisponível. Tente novamente em instantes." : "Não foi possível concluir a ação. Verifique os dados e tente novamente.");
  }
  if (response.status === 204) return null;
  try { return await response.json(); }
  catch { throw new Error("O servidor respondeu em um formato inesperado. Tente novamente."); }
}

async function loadCredentials() {
  const version = ++credentialsVersion;
  const list = $("credentials-list");
  list.replaceChildren();
  const loading = document.createElement("p");
  loading.className = "empty-state";
  loading.textContent = "Carregando suas contas…";
  list.append(loading);
  $("refresh-button").disabled = true;
  try {
    const credentials = await api("/api/oauth/credentials");
    if (version !== credentialsVersion || !["home", "chat"].includes(state.screen)) return;
    if (!Array.isArray(credentials)) throw new Error("A lista de contas veio em um formato inesperado. Atualize para tentar novamente.");
    state.credentials = credentials;
    const picker = $("chat-credential");
    const selected = picker.value;
    picker.replaceChildren();
    for (const credential of credentials) {
      if (!credential || typeof credential.credential_id !== "string") continue;
      const option = new Option(`${credential.credential_id}${credential.connected ? "" : " · desconectada"}`, credential.credential_id);
      option.disabled = !credential.connected;
      picker.add(option);
    }
    if ([...picker.options].some(option => option.value === selected && !option.disabled)) picker.value = selected;
    else picker.value = [...picker.options].find(option => !option.disabled)?.value || "";
    const connectedCount = [...picker.options].filter(option => !option.disabled).length;
    document.querySelector(".credential-picker").hidden = connectedCount <= 1;
    $("chat-header-accounts").hidden = connectedCount !== 0;
    list.replaceChildren();
    if (!credentials.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Nenhuma conta foi atribuída a você. Peça acesso ao responsável da Castelo Branco.";
      list.append(empty);
      return;
    }
    for (const credential of credentials) {
      if (!credential || typeof credential.credential_id !== "string") continue;
      const row = document.createElement("article");
      row.className = "credential";
      const marker = document.createElement("img");
      marker.className = "credential-marker";
      marker.src = "/maximus-mark.svg";
      marker.alt = "";
      const info = document.createElement("div");
      info.className = "credential-info";
      const title = document.createElement("strong");
      title.textContent = credential.credential_id;
      const description = document.createElement("span");
      description.textContent = credential.connected ? "Conectada" : "Aguardando conexão";
      info.append(title, description);
      row.append(marker, info);
      if (credential.can_connect === true) {
        const button = document.createElement("button");
        button.className = "secondary-button";
        button.type = "button";
        button.textContent = credential.connected ? "Renovar conexão" : "Conectar conta";
        button.addEventListener("click", () => startConnection(credential, button));
        row.append(button);
      } else {
        const note = document.createElement("span");
        note.className = "coming-soon";
        note.textContent = credential.connected ? "Pronta para uso" : "Aguardando responsável";
        row.append(note);
      }
      list.append(row);
    }
  } catch (error) {
    if (version !== credentialsVersion || !["home", "chat"].includes(state.screen)) return;
    if (state.screen === "chat") $("chat-header-accounts").hidden = false;
    list.replaceChildren();
    const failure = document.createElement("p");
    failure.className = "empty-state";
    failure.textContent = error.message;
    list.append(failure);
  } finally {
    if (version === credentialsVersion) $("refresh-button").disabled = false;
  }
}

async function restore() {
  try {
    state.employee = await api("/api/auth/me");
    if (state.employee.must_change_password) show("password");
    else await enterWorkspace();
  } catch (error) {
    if (state.screen !== "login") clearSession();
    if (!error.message.includes("Sua sessão terminou")) status(error.message, true);
  }
}

$("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  formError("login-error", "");
  setBusy(form, true);
  try {
    await api("/api/auth/login", { method: "POST", body: JSON.stringify({ employee_code: $("employee-code").value.trim(), password: $("login-password").value }) });
    $("login-password").value = "";
    state.employee = await api("/api/auth/me");
    if (state.employee.must_change_password) show("password");
    else await enterWorkspace();
  } catch (error) {
    if (state.screen === "login") formError("login-error", error.message);
  } finally { setBusy(form, false); }
});

$("password-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  formError("password-error", "");
  if ($("new-password").value !== $("confirm-password").value) {
    formError("password-error", "As novas senhas não coincidem.");
    $("confirm-password").focus();
    return;
  }
  setBusy(form, true);
  try {
    await api("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password: $("current-password").value, new_password: $("new-password").value }) });
    form.reset();
    state.employee = await api("/api/auth/me");
    await enterWorkspace();
  } catch (error) {
    if (state.screen === "password") formError("password-error", error.message);
  } finally { setBusy(form, false); }
});

$("logout-button").addEventListener("click", async () => {
  const button = $("logout-button");
  button.disabled = true;
  try { await api("/api/auth/logout", { method: "POST" }); clearSession(); }
  catch (error) { if (state.screen !== "login") status(error.message, true); }
  finally { button.disabled = false; }
});

$("refresh-button").addEventListener("click", loadCredentials);
$("chat-nav").addEventListener("click", async () => { show("chat"); await loadProjects(); await loadChat(); await loadConversations(); });
$("accounts-nav").addEventListener("click", () => { show("home"); loadCredentials(); });
$("chat-header-accounts").addEventListener("click", () => $("accounts-nav").click());
$("chat-header-logout").addEventListener("click", () => $("logout-button").click());
$("chat-side-user").addEventListener("click", () => setChatUserMenu($("chat-user-menu").hidden));
$("chat-sidebar-logout").addEventListener("click", () => { setChatUserMenu(false); $("logout-button").click(); });
document.addEventListener("click", event => {
  if (!$("chat-side-user").parentElement.contains(event.target)) setChatUserMenu(false);
  if (!$("chat-add-menu").contains(event.target)) $("chat-add-menu").open = false;
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("chat-user-menu").hidden) { setChatUserMenu(false); $("chat-side-user").focus(); }
  if (event.key === "Escape" && $("chat-add-menu").open) { $("chat-add-menu").open = false; $("chat-add-menu").querySelector("summary").focus(); }
});

function renderProjects() {
  const list = $("chat-project-list");
  list.replaceChildren();
  $("chat-project-general").classList.toggle("active", !state.chat.projectId);
  $("chat-list-heading").textContent = state.projects.find(item => item.id === state.chat.projectId)?.name || "Recentes";
  for (const project of state.projects) {
    const row = document.createElement("div");
    row.className = "chat-project-row";
    row.classList.toggle("active", project.id === state.chat.projectId);
    const open = document.createElement("button");
    open.type = "button";
    open.className = "chat-project-open";
    open.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-folder"/></svg>';
    open.append(document.createTextNode(project.name));
    open.addEventListener("click", () => selectProject(project.id));
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "chat-project-trigger";
    trigger.textContent = "⋯";
    trigger.setAttribute("aria-label", `Opções do projeto ${project.name}`);
    const menu = document.createElement("div");
    menu.className = "chat-conversation-menu";
    menu.setAttribute("popover", "auto");
    menu.setAttribute("role", "menu");
    trigger.addEventListener("click", () => {
      if (menu.matches(":popover-open")) { menu.hidePopover(); return; }
      const rect = trigger.getBoundingClientRect();
      menu.style.left = `${Math.min(rect.right + 8, window.innerWidth - 220)}px`;
      menu.style.top = `${Math.max(12, Math.min(rect.top - 8, window.innerHeight - 110))}px`;
      menu.showPopover();
    });
    const rename = document.createElement("button");
    rename.type = "button";
    rename.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-edit"/></svg><span>Renomear projeto</span>';
    rename.addEventListener("click", () => { menu.hidePopover(); openProjectDialog(project); });
    const context = document.createElement("button");
    context.type = "button";
    context.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-book"/></svg><span>Contexto do projeto</span>';
    context.addEventListener("click", () => {
      menu.hidePopover();
      selectProject(project.id);
      openContextDialog("project");
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-trash"/></svg><span>Excluir projeto</span>';
    remove.addEventListener("click", async () => {
      menu.hidePopover();
      if (!window.confirm(`Excluir o projeto “${project.name}”? As conversas voltarão para “Sem projeto”.`)) return;
      try {
        await api(`/api/chat/projects/${project.id}`, { method: "DELETE" });
        if (state.chat.projectId === project.id) state.chat.projectId = null;
        await loadProjects();
        if (state.chat.conversationId) await loadChat();
        else renderChat();
        await loadConversations();
      } catch (error) { status(error.message, true); }
    });
    menu.append(rename, context, remove);
    row.append(open, trigger, menu);
    list.append(row);
  }
}

async function loadProjects() {
  try {
    state.projects = (await api("/api/chat/projects")).projects;
    renderProjects();
  } catch (error) { if (state.screen === "chat") status(error.message, true); }
}

async function selectProject(projectId) {
  if (state.chat.busy) return;
  if (state.chat.projectId === projectId && state.chat.conversationId) {
    document.querySelector(".chat-shell")?.classList.remove("mobile-conversations");
    return;
  }
  $("status").hidden = true;
  state.chat.projectId = projectId;
  state.chat.search = "";
  $("chat-search").value = "";
  state.chat.conversations = [];
  $("chat-new").click();
  const version = chatVersion;
  renderProjects();
  await loadConversations();
  if (version === chatVersion && state.chat.projectId === projectId && state.chat.conversations.length) {
    $("chat-conversations").querySelector(".chat-conversation-open")?.click();
  }
}

function openProjectDialog(project = null) {
  $("project-dialog").dataset.projectId = project?.id || "";
  $("project-dialog-title").textContent = project ? "Renomear projeto" : "Novo projeto";
  $("project-name").value = project?.name || "";
  $("project-dialog").showModal();
  $("project-name").focus();
}

$("chat-project-general").addEventListener("click", () => selectProject(null));
$("chat-project-new").addEventListener("click", () => openProjectDialog());
$("project-cancel").addEventListener("click", () => $("project-dialog").close());
$("project-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = $("project-name").value.trim();
  if (!name) return;
  const projectId = $("project-dialog").dataset.projectId;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const project = await api(projectId ? `/api/chat/projects/${projectId}` : "/api/chat/projects", {
      method: projectId ? "PATCH" : "POST", body: JSON.stringify({ name }) });
    $("project-dialog").close();
    await loadProjects();
    if (!projectId) selectProject(project.id);
    else if (state.chat.projectId === projectId) renderChat();
  } catch (error) { status(error.message, true); }
  finally { button.disabled = false; }
});

function contextTarget(scope) {
  return scope === "project" ? state.chat.projectId :
    scope === "conversation" ? state.chat.conversationId : null;
}

function resetContextForm() {
  $("context-form").reset();
  delete $("context-form").dataset.noteId;
  $("context-kind").disabled = false;
  $("context-cancel-edit").hidden = true;
  $("context-form").querySelector('button[type="submit"]').textContent = "Adicionar";
  $("context-error").hidden = true;
}

function openContextDialog(scope = "profile") {
  $("context-scope").querySelector('[value="project"]').disabled = !state.chat.projectId;
  $("context-scope").querySelector('[value="conversation"]').disabled = !state.chat.conversationId;
  $("context-scope").value = contextTarget(scope) ? scope : "profile";
  resetContextForm();
  profileDirty = false;
  $("context-dialog").showModal();
  loadContextNotes();
}

async function loadContextNotes() {
  const scope = $("context-scope").value;
  const target = contextTarget(scope);
  const params = new URLSearchParams({ scope });
  if (target) params.set("target_id", target);
  const list = $("context-list");
  list.textContent = "Carregando contexto…";
  $("profile-form").hidden = scope !== "profile";
  $("context-list-label").textContent = scope === "profile" ? "Notas adicionais" : "Notas deste contexto";
  try {
    const [result, profile] = await Promise.all([
      api(`/api/chat/context?${params}`),
      scope === "profile" ? api("/api/chat/profile") : Promise.resolve(null),
    ]);
    if (!$("context-dialog").open || scope !== $("context-scope").value) return;
    if (profile && !profileDirty) $("profile-text").value = profile.text;
    const { notes } = result;
    list.replaceChildren();
    if (!notes.length) {
      const empty = document.createElement("p");
      empty.textContent = "Nenhuma instrução ou memória salva neste nível.";
      list.append(empty);
    }
    for (const note of notes) {
      const row = document.createElement("div");
      row.className = "context-note";
      const label = document.createElement("small");
      label.textContent = `${note.kind === "instruction" ? "Instrução" : "Memória"}${note.automatic ? " · criada pela IA" : ""}`;
      const content = document.createElement("p");
      content.textContent = note.content;
      const actions = document.createElement("div");
      actions.className = "context-note-actions";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Editar";
      edit.addEventListener("click", () => {
        $("context-form").dataset.noteId = note.id;
        $("context-kind").value = note.kind;
        $("context-kind").disabled = true;
        $("context-content").value = note.content;
        $("context-cancel-edit").hidden = false;
        $("context-form").querySelector('button[type="submit"]').textContent = "Salvar alteração";
        $("context-content").focus();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Excluir";
      remove.addEventListener("click", async () => {
        if (!window.confirm("Excluir esta nota de contexto?")) return;
        try {
          await api(`/api/chat/context/${note.id}`, { method: "DELETE" });
          resetContextForm();
          await loadContextNotes();
        } catch (error) { formError("context-error", error.message); }
      });
      actions.append(edit, remove);
      row.append(label, content, actions);
      list.append(row);
    }
  } catch (error) { formError("context-error", error.message); }
}

$("chat-context").addEventListener("click", () => openContextDialog(
  state.chat.conversationId ? "conversation" : state.chat.projectId ? "project" : "profile"));
$("chat-menu-context").addEventListener("click", () => { setChatUserMenu(false); openContextDialog("profile"); });
$("context-close").addEventListener("click", () => $("context-dialog").close());
$("profile-text").addEventListener("input", () => { profileDirty = true; });
$("profile-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const profile = await api("/api/chat/profile", {
      method: "PATCH", body: JSON.stringify({ text: $("profile-text").value }),
    });
    $("profile-text").value = profile.text;
    profileDirty = false;
    formError("profile-error", "");
  } catch (error) { formError("profile-error", error.message); }
  finally { button.disabled = false; }
});
$("context-cancel-edit").addEventListener("click", resetContextForm);
$("context-scope").addEventListener("change", () => { resetContextForm(); loadContextNotes(); });
$("context-form").addEventListener("submit", async event => {
  event.preventDefault();
  const content = $("context-content").value.trim();
  if (!content) return;
  const noteId = event.currentTarget.dataset.noteId;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api(noteId ? `/api/chat/context/${noteId}` : "/api/chat/context", {
      method: noteId ? "PATCH" : "POST",
      body: JSON.stringify(noteId ? { content } : {
        scope: $("context-scope").value, target_id: contextTarget($("context-scope").value),
        kind: $("context-kind").value, content,
      }),
    });
    resetContextForm();
    await loadContextNotes();
  } catch (error) { formError("context-error", error.message); }
  finally { button.disabled = false; }
});

$("chat-new").addEventListener("click", () => {
  if (state.chat.busy) return;
  chatVersion++;
  state.chat.conversationId = null;
  state.chat.title = null;
  state.chat.runs = [];
  state.chat.before = null;
  state.chat.pending = null;
  state.chat.preview = null;
  $("chat-more").hidden = true;
  document.querySelector(".chat-shell")?.classList.remove("mobile-conversations");
  renderChat();
  $("chat-text").focus();
});
$("chat-mobile-list").addEventListener("click", () => {
  document.querySelector(".chat-shell")?.classList.toggle("mobile-conversations");
});
$("chat-mobile-close").addEventListener("click", () => {
  document.querySelector(".chat-shell")?.classList.remove("mobile-conversations");
  $("chat-mobile-list").focus();
});
let searchTimer;
$("chat-search").addEventListener("input", event => {
  state.chat.search = event.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadConversations(), 250);
});
$("chat-list-more").addEventListener("click", () => loadConversations(state.chat.listBefore));
function editConversationTitle() {
  $("chat-title-input").value = state.chat.title || "";
  $("chat-title-form").hidden = false;
  $("chat-title-input").focus();
}
$("chat-title-cancel").addEventListener("click", () => { $("chat-title-form").hidden = true; });
$("chat-title-input").addEventListener("keydown", event => {
  if (event.key === "Escape") { $("chat-title-form").hidden = true; $("chat-search").focus(); }
});
$("chat-title-form").addEventListener("submit", async event => {
  event.preventDefault();
  const title = $("chat-title-input").value.trim();
  if (!title) return;
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api(`/api/chat/conversations/${state.chat.conversationId}`, { method: "PATCH", body: JSON.stringify({ title }) });
    state.chat.title = result.title;
    $("chat-title-form").hidden = true;
    renderChat();
    loadConversations();
  } catch (error) { status(error.message, true); }
  finally { button.disabled = false; }
});
for (const id of ["governance-nav", "chat-sidebar-governance", "chat-menu-governance"]) {
  $(id).addEventListener("click", () => { show("governance"); loadGovernance(); });
}
$("back-button").addEventListener("click", () => { state.connection = null; $("callback-form").reset(); show("home"); loadCredentials(); });

async function startConnection(credential, button) {
  if (credential.can_connect !== true) return;
  const version = sessionVersion;
  button.disabled = true;
  const tab = window.open("", "_blank");
  if (tab) tab.opener = null;
  try {
    const result = await api(`/api/oauth/credentials/${encodeURIComponent(credential.credential_id)}/start`, { method: "POST" });
    if (version !== sessionVersion) { tab?.close(); return; }
    const authorize = new URL(result.authorize_url);
    if (authorize.protocol !== "https:") throw new Error("O endereço de autorização é inválido. Tente novamente.");
    state.connection = { id: result.connection_id, credentialId: credential.credential_id, startedAt: Date.now() };
    $("connect-description").textContent = `Você está conectando ${credential.credential_id}. Mantenha esta aba aberta durante a autorização.`;
    $("authorize-link").href = authorize.href;
    $("authorize-fallback").hidden = false;
    $("callback-form").reset();
    formError("callback-error", "");
    show("connect");
    if (tab) tab.location.href = authorize.href;
    else status("Seu navegador bloqueou a nova aba. Use o link para abrir a página de autorização.");
  } catch (error) {
    tab?.close();
    if (["home", "chat"].includes(state.screen)) status(error.message, true);
  } finally { button.disabled = false; }
}

$("callback-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  formError("callback-error", "");
  const connection = state.connection;
  const version = sessionVersion;
  if (!connection || Date.now() - connection.startedAt >= 10 * 60 * 1000) {
    state.connection = null;
    formError("callback-error", "O prazo terminou. Volte às contas e inicie a conexão novamente.");
    return;
  }
  setBusy(form, true);
  try {
    await api(`/api/oauth/connections/${encodeURIComponent(connection.id)}/complete`, { method: "POST", body: JSON.stringify({ callback_url: $("callback-url").value.trim() }) });
    if (version !== sessionVersion) return;
    state.connection = null;
    form.reset();
    show("home");
    status(`Conta ${connection.credentialId} conectada.`);
    await loadCredentials();
    if (state.chat.pending?.phase === "reconnect") {
      state.chat.pending.phase = "sending";
      state.chat.pending.retried = true;
      show("chat");
      await sendChatMessage(state.chat.pending);
    }
  } catch (error) {
    if (state.screen === "connect") {
      if (error.message.includes("pedido expirou")) state.connection = null;
      formError("callback-error", error.message);
    }
  } finally { setBusy(form, false); }
});

async function enterWorkspace() {
  if (state.employee.role === "governance") {
    show("governance");
    await loadGovernance();
  } else {
    show("chat");
    await Promise.all([loadCredentials(), loadProjects()]);
    await loadChat();
    await loadConversations();
  }
}

function assistantText(response) {
  if (!response || !Array.isArray(response.output)) return "";
  return response.output.filter(item => item?.type === "message" && item.role === "assistant")
    .flatMap(item => Array.isArray(item.content) ? item.content : [])
    .map(part => part?.type === "output_text" ? part.text : part?.type === "refusal" ? part.refusal : "")
    .filter(text => typeof text === "string").join("\n");
}

function requestsPdf(text) {
  const normalized = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  if (/\bnao (quero|gere|gerar|crie|criar)\b|\bsem pdf\b/.test(normalized)) return false;
  const hasContent = /\b(resumo|relatorio|documento|texto|conteudo|dados|tabela|lista|carta|guia|artigo|historia|livro|resposta)\b/.test(normalized);
  return /\bpdf\b/.test(normalized)
    && /\b(crie|criar|gere|gerar|faca|fazer|monte|produza|exporte|transforme|converta|quero|preciso|entregue|envie)\b/.test(normalized)
    && (hasContent || !/\b(consegue|pode|possivel)\b|tem como/.test(normalized));
}

function fileCard(file, onRemove) {
  const extension = file.name.split(".").at(-1).toLowerCase();
  const kind = ["png", "jpg", "jpeg", "webp", "gif"].includes(extension) ? "image"
    : ["csv", "tsv", "xls", "xlsx"].includes(extension) ? "table"
    : ["ppt", "pptx"].includes(extension) ? "slides" : "file";
  const iconName = { image: "icon-file-image", table: "icon-file-table",
    slides: "icon-file-slides", file: "icon-file" }[kind];
  const card = document.createElement(file.id && !onRemove ? "button" : "div");
  card.className = "chat-file-card";
  card.dataset.kind = kind;
  if (file.id && !onRemove) {
    card.type = "button";
    card.setAttribute("aria-label", `Visualizar ${file.name}`);
    card.addEventListener("click", () => openFilePreview(file));
  }
  const emblem = document.createElement("span");
  emblem.className = "chat-file-emblem";
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", "ui-icon");
  icon.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${iconName}`);
  icon.append(use);
  emblem.append(icon);
  const details = document.createElement("span");
  details.className = "chat-file-details";
  const name = document.createElement("strong");
  name.textContent = file.name;
  name.title = file.name;
  const meta = document.createElement("small");
  const size = typeof file.size === "number"
    ? ` · ${file.size < 1000 ? `${file.size} B` : file.size < 1_000_000
      ? `${(file.size / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} KB`
      : `${(file.size / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`}` : "";
  meta.textContent = `${extension.toUpperCase()}${size}`;
  details.append(name, meta);
  card.append(emblem, details);
  if (onRemove) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chat-file-remove";
    remove.setAttribute("aria-label", `Remover ${file.name}`);
    const close = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    close.setAttribute("class", "ui-icon");
    close.setAttribute("aria-hidden", "true");
    const closeUse = document.createElementNS("http://www.w3.org/2000/svg", "use");
    closeUse.setAttribute("href", "#icon-close");
    close.append(closeUse);
    remove.append(close);
    remove.addEventListener("click", onRemove);
    card.append(remove);
  }
  return card;
}

async function openFilePreview(file) {
  const dialog = $("artifact-dialog");
  const body = $("artifact-dialog-body");
  const path = `/api/chat/${file.format ? "artifacts" : "attachments"}/${encodeURIComponent(file.id)}`;
  const key = `${file.format || "attachment"}:${file.id}`;
  const extension = file.name.split(".").at(-1).toLowerCase();
  dialog.dataset.fileKey = key;
  $("artifact-dialog-title").textContent = file.name;
  $("artifact-dialog-download").href = path;
  $("artifact-dialog-download").download = file.name;
  $("artifact-dialog-note").textContent = "";
  body.replaceChildren();
  if (!dialog.open) dialog.showModal();
  if (extension === "pdf") {
    const frame = document.createElement("iframe");
    frame.title = `Prévia de ${file.name}`;
    frame.src = `${path}/preview`;
    body.append(frame);
    $("artifact-dialog-note").textContent = "Documento PDF";
    return;
  }
  if (["png", "jpg", "jpeg", "webp", "gif"].includes(extension)) {
    const picture = document.createElement("img");
    picture.alt = `Prévia de ${file.name}`;
    picture.src = `${path}/preview`;
    body.append(picture);
    return;
  }
  if (!["csv", "tsv", "xlsx", "txt", "md", "json", "xml", "html", "py", "js", "ts", "css", "sql", "yaml", "yml"].includes(extension)) {
    body.textContent = "A prévia não está disponível para este formato. Você pode baixar o arquivo original.";
    return;
  }
  body.textContent = "Carregando prévia…";
  try {
    const preview = await api(`${path}/preview`);
    if (!dialog.open || dialog.dataset.fileKey !== key) return;
    if ("text" in preview) {
      const content = document.createElement("pre");
      content.className = "chat-file-text-preview";
      content.textContent = preview.text;
      body.replaceChildren(content);
      $("artifact-dialog-note").textContent = preview.truncated ? "Exibindo os primeiros 200 KB. Baixe o arquivo para ver todo o conteúdo." : "Arquivo de texto";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const heading = document.createElement("tr");
    for (const value of preview.columns) {
      const cell = document.createElement("th");
      cell.textContent = value;
      heading.append(cell);
    }
    thead.append(heading);
    const tbody = document.createElement("tbody");
    for (const row of preview.rows) {
      const line = document.createElement("tr");
      for (const value of row) {
        const cell = document.createElement("td");
        cell.textContent = value;
        line.append(cell);
      }
      tbody.append(line);
    }
    table.append(thead, tbody);
    body.replaceChildren(table);
    $("artifact-dialog-note").textContent = preview.truncated
      ? "Exibindo as primeiras 100 linhas. Baixe o arquivo para ver todas."
      : `${preview.rows.length} ${preview.rows.length === 1 ? "linha" : "linhas"}`;
  } catch (error) {
    if (dialog.open && dialog.dataset.fileKey === key) body.textContent = error.message;
  }
}

$("artifact-dialog-close").addEventListener("click", () => $("artifact-dialog").close());

function chatBubble(role, text, note, attachments = []) {
  const article = document.createElement("article");
  article.className = `chat-bubble ${role}`;
  const body = document.createElement("div");
  body.className = "chat-content";
  if (role === "assistant") body.innerHTML = markdown.render(text || "");
  else body.textContent = text;
  if (text) article.append(body);
  if (attachments.length) {
    const files = document.createElement("div");
    files.className = "chat-file-list";
    for (const file of attachments) files.append(fileCard(file));
    article.append(files);
  }
  if (note) {
    const small = document.createElement("small");
    small.textContent = note;
    article.append(small);
  }
  return article;
}

function artifactControls(run, bubble) {
  if (run.artifacts?.length) {
    const files = document.createElement("div");
    files.className = "chat-file-list";
    for (const artifact of run.artifacts) files.append(fileCard(artifact));
    bubble.append(files);
  }
  const menu = document.createElement("details");
  menu.className = "chat-artifact-menu";
  const summary = document.createElement("summary");
  summary.textContent = "Criar arquivo";
  menu.append(summary);
  const choices = document.createElement("div");
  for (const format of ["pdf", "xlsx", "csv"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = format.toUpperCase();
    button.addEventListener("click", async () => {
      choices.querySelectorAll("button").forEach(item => { item.disabled = true; });
      summary.textContent = "Criando arquivo…";
      try {
        const artifact = await api(`/api/chat/runs/${run.run_id}/artifacts`, {
          method: "POST", body: JSON.stringify({ format })
        });
        run.artifacts ||= [];
        if (!run.artifacts.some(item => item.id === artifact.id)) run.artifacts.push(artifact);
        renderChat();
        openFilePreview(artifact);
      } catch (error) {
        summary.textContent = "Criar arquivo";
        choices.querySelectorAll("button").forEach(item => { item.disabled = false; });
        status(error.message, true);
      }
    });
    choices.append(button);
  }
  menu.append(choices);
  bubble.append(menu);
}

function renderChat() {
  const transcript = $("chat-transcript");
  transcript.replaceChildren();
  const runs = [...state.chat.runs].reverse();
  const projectName = state.projects.find(item => item.id === state.chat.projectId)?.name;
  const topic = state.chat.title || (state.chat.conversationId ? "Conversa sem título" : projectName ? `Novo chat · ${projectName}` : "Nova conversa");
  $("chat-topic").textContent = topic;
  renderConversationList();
  $("chat-sidebar-employee").textContent = state.employee?.employee_code || "";
  if (!runs.length && !state.chat.pending) {
    const empty = document.createElement("div");
    empty.className = "chat-empty";
    empty.innerHTML = '<span class="chat-empty-mark" aria-hidden="true"></span><h2>Como posso ajudar hoje?</h2><p>Sou o Maximus, seu assistente de IA da Castelo Branco.<br>Faça perguntas, analise documentos e explore novas ideias.</p>';
    transcript.append(empty);
  }
  for (const run of runs) {
    if (typeof run.prompt === "string") {
      const bubble = chatBubble("user", run.prompt, null, run.attachments);
      bubble.dataset.runId = run.run_id;
      bubble.dataset.role = "user";
      transcript.append(bubble);
    }
    const answer = assistantText(run.response) || (state.chat.preview?.id === run.client_message_id ? state.chat.preview.answer : "");
    if (answer) {
      const bubble = chatBubble("assistant", answer);
      bubble.dataset.runId = run.run_id;
      bubble.dataset.role = "assistant";
      if (run.outcome === "completed") artifactControls(run, bubble);
      transcript.append(bubble);
    }
    else if (run.outcome !== "completed") transcript.append(chatBubble("assistant", "", run.outcome === "open" ? "Resposta em andamento" : "Resposta indisponível. A mensagem não foi reenviada."));
  }
  const pending = state.chat.pending;
  if (pending && !runs.some(run => run.client_message_id === pending.id)) {
    transcript.append(chatBubble("user", pending.text, null, pending.fileCards || pending.attachments));
    const note = pending.phase === "sending" ? "Respondendo…" : pending.phase === "reconnect" ? "Aguardando reconexão" : pending.error || "Envio não confirmado";
    transcript.append(chatBubble("assistant", pending.answer || "", note));
  }
  $("chat-reconnect").hidden = pending?.phase !== "reconnect";
  if (pending?.phase === "reconnect") {
    const canConnect = state.credentials.some(item => item.credential_id === pending.credentialId && item.can_connect);
    $("chat-reconnect-text").textContent = canConnect
      ? `A conta ${pending.credentialId} precisa ser reconectada. Sua mensagem foi preservada e será enviada uma vez após a conexão.`
      : `A conta ${pending.credentialId} precisa ser reconectada pelo responsável. Sua mensagem foi preservada nesta aba.`;
    $("chat-reconnect-button").hidden = !canConnect;
  }
  $("chat-form").querySelector("button[type=submit]").disabled = state.chat.busy || audioBusy || !!audioRecorder || pending?.phase === "reconnect";
  $("chat-audio-file").disabled = state.chat.busy || audioBusy || !!audioRecorder;
  $("chat-add-audio").disabled = state.chat.busy || audioBusy || !!audioRecorder;
  $("chat-record").disabled = state.chat.busy || audioBusy;
  transcript.scrollTop = transcript.scrollHeight;
}

function renderConversationList() {
  const list = $("chat-conversations");
  list.replaceChildren();
  if (!state.chat.conversations.length) {
    const empty = document.createElement("p");
    empty.className = "chat-list-empty";
    empty.textContent = state.chat.search ? "Nenhuma conversa encontrada" : "Nenhuma conversa ainda";
    list.append(empty);
  }
  for (const conversation of state.chat.conversations) {
    const row = document.createElement("div");
    row.className = "chat-recent-row";
    if (conversation.id === state.chat.conversationId) row.classList.add("active");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "chat-conversation-open";
    open.textContent = conversation.title || "Conversa sem título";
    if (conversation.snippet) {
      const snippet = document.createElement("small");
      snippet.textContent = conversation.snippet;
      open.append(snippet);
    }
    open.addEventListener("click", async () => {
      if (state.chat.busy) return;
      state.chat.conversationId = conversation.id;
      state.chat.projectId = conversation.project_id || null;
      state.chat.title = conversation.title;
      state.chat.preview = null;
      state.chat.pending = null;
      renderProjects();
      await loadChat();
      while (conversation.match_run_id && state.chat.before &&
             !state.chat.runs.some(run => run.run_id === conversation.match_run_id)) {
        await loadChat(state.chat.before);
      }
      if (conversation.match_run_id) {
        $("chat-transcript").querySelector(`[data-run-id="${conversation.match_run_id}"][data-role="${conversation.match_role || "user"}"]`)?.scrollIntoView({ block: "center" });
      }
      document.querySelector(".chat-shell")?.classList.remove("mobile-conversations");
    });
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "chat-conversation-trigger";
    trigger.textContent = "⋯";
    trigger.setAttribute("aria-label", `Opções para ${conversation.title || "Conversa sem título"}`);
    trigger.setAttribute("aria-haspopup", "menu");
    trigger.setAttribute("aria-expanded", "false");
    const menu = document.createElement("div");
    menu.className = "chat-conversation-menu";
    menu.setAttribute("popover", "auto");
    menu.setAttribute("role", "menu");
    menu.addEventListener("toggle", () => trigger.setAttribute("aria-expanded", String(menu.matches(":popover-open"))));
    trigger.addEventListener("click", () => {
      if (menu.matches(":popover-open")) { menu.hidePopover(); return; }
      const rect = trigger.getBoundingClientRect();
      menu.style.left = `${Math.min(rect.right + 8, window.innerWidth - 220)}px`;
      menu.style.top = `${Math.max(12, Math.min(rect.top - 8, window.innerHeight - 330))}px`;
      menu.showPopover();
    });
    const edit = document.createElement("button");
    edit.type = "button";
    edit.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-edit"/></svg><span>Renomear</span>';
    edit.addEventListener("click", async () => {
      if (state.chat.busy) return;
      menu.hidePopover();
      state.chat.conversationId = conversation.id;
      state.chat.title = conversation.title;
      await loadChat();
      editConversationTitle();
    });
    const move = document.createElement("button");
    move.type = "button";
    move.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-folder"/></svg><span>Mover para projeto</span>';
    const choices = document.createElement("div");
    choices.className = "chat-move-choices";
    choices.hidden = true;
    move.addEventListener("click", () => { choices.hidden = !choices.hidden; });
    for (const project of [{ id: null, name: "Sem projeto" }, ...state.projects]) {
      const choice = document.createElement("button");
      choice.type = "button";
      choice.textContent = project.name;
      choice.disabled = (conversation.project_id || null) === project.id;
      choice.addEventListener("click", async () => {
        try {
          await api(`/api/chat/conversations/${conversation.id}/project`, {
            method: "PATCH", body: JSON.stringify({ project_id: project.id }) });
          menu.hidePopover();
          if (state.chat.conversationId === conversation.id) {
            state.chat.projectId = project.id;
            renderProjects();
            await loadChat();
          }
          await loadConversations();
        } catch (error) { status(error.message, true); }
      });
      choices.append(choice);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#icon-trash"/></svg><span>Excluir</span>';
    remove.addEventListener("click", async () => {
      menu.hidePopover();
      if (state.chat.busy || !window.confirm(`Excluir a conversa “${conversation.title || "Conversa sem título"}”?`)) return;
      try {
        await api(`/api/chat/conversations/${conversation.id}`, { method: "DELETE" });
        if (state.chat.conversationId === conversation.id) $("chat-new").click();
        await loadConversations();
      } catch (error) { status(error.message, true); }
    });
    menu.append(edit, move, choices, remove);
    row.append(open, trigger, menu);
    list.append(row);
  }
}

async function loadConversations(before = null) {
  const search = state.chat.search;
  const projectId = state.chat.projectId;
  try {
    const params = new URLSearchParams({ limit: "50" });
    if (search) params.set("q", search);
    else if (projectId) params.set("project_id", projectId);
    else params.set("unassigned", "true");
    if (before) params.set("before", before);
    const result = await api(`/api/chat/conversations?${params}`);
    if (state.screen !== "chat" || search !== state.chat.search || projectId !== state.chat.projectId) return;
    state.chat.conversations = before ? [...state.chat.conversations, ...result.conversations] : result.conversations;
    state.chat.listBefore = result.next_before;
    $("chat-list-more").hidden = !result.next_before;
    renderConversationList();
  } catch (error) { if (state.screen === "chat") status(error.message, true); }
}

async function loadChat(before = null) {
  const version = ++chatVersion;
  if (!before && !state.chat.conversationId && state.chat.projectId) {
    state.chat.runs = [];
    state.chat.before = null;
    renderChat();
    return;
  }
  try {
    const result = await api(`/api/chat/history?limit=50${state.chat.conversationId ? `&conversation_id=${encodeURIComponent(state.chat.conversationId)}` : ""}${before ? `&before=${encodeURIComponent(before)}` : ""}`);
    if (version !== chatVersion || state.screen !== "chat") return;
    if (!Array.isArray(result.runs)) throw new Error("O histórico veio em um formato inesperado.");
    if (!before) {
      state.chat.conversationId = result.conversation_id;
      state.chat.title = result.title;
      if (result.conversation_id) { state.chat.projectId = result.project_id || null; renderProjects(); }
    }
    state.chat.runs = before ? [...state.chat.runs, ...result.runs] : result.runs;
    state.chat.before = result.runs.length === 50 ? result.runs.at(-1).run_id : null;
    $("chat-more").hidden = !state.chat.before;
    renderChat();
  } catch (error) { if (version === chatVersion && state.screen === "chat") status(error.message, true); }
}

function applyStreamEvent(eventName, data, pending) {
  let payload;
  try { payload = JSON.parse(data); } catch { return; }
  const type = eventName || payload.type;
  if (type === "response.output_text.delta" && typeof payload.delta === "string") pending.answer += payload.delta;
  if (type === "response.completed") pending.answer = assistantText(payload.response) || pending.answer;
  if (type === "response.failed" || type === "response.incomplete" || type === "error") pending.error = "A IA não conseguiu processar esta mensagem ou arquivo. Confira o formato e tente novamente.";
  renderChat();
}

async function readChatStream(response, pending) {
  if (!response.body) throw new Error("O servidor não abriu o fluxo de resposta.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop();
    for (const frame of frames) {
      const lines = frame.split(/\r?\n/);
      const eventName = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
      if (data && data !== "[DONE]") applyStreamEvent(eventName, data, pending);
    }
    if (done) {
      if (buffer.trim()) {
        const lines = buffer.split(/\r?\n/);
        const eventName = lines.find(line => line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (data && data !== "[DONE]") applyStreamEvent(eventName, data, pending);
      }
      return;
    }
  }
}

async function sendChatMessage(pending) {
  const version = sessionVersion;
  state.chat.busy = true;
  renderChat();
  try {
    const response = await fetch("/api/chat/messages", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "Accept": "text/event-stream" }, body: JSON.stringify({ client_message_id: pending.id, credential_id: pending.credentialId, model: "gpt-6-luna", text: pending.text, attachments: pending.attachments, conversation_id: pending.conversationId, new_conversation: !pending.conversationId, project_id: pending.conversationId ? null : pending.projectId }) });
    if (version !== sessionVersion) return;
    if (response.status === 401) { clearSession(); return; }
    if (response.status === 409) {
      const conflict = await response.json();
      const detail = conflict.detail || conflict;
      if (detail.code === "reconnect_required" && !pending.retried) {
        pending.phase = "reconnect";
        renderChat();
        return;
      }
      if (detail.code === "duplicate_message" && detail.run_id) {
        await api(`/api/chat/runs/${encodeURIComponent(detail.run_id)}`);
        state.chat.pending = null;
        await loadChat();
        return;
      }
      throw new Error("A conversa está ocupada ou precisa ser reconectada. Confira o histórico antes de tentar novamente.");
    }
    if (!response.ok) throw new Error(response.status === 429 ? "Limite de uso atingido. Aguarde antes de enviar outra mensagem." : [413, 422].includes(response.status) ? "Formato ou tamanho de arquivo não aceito. Revise os anexos e tente novamente." : "Não foi possível confirmar a entrega. Confira o histórico antes de tentar novamente.");
    if (!response.headers.get("content-type")?.includes("text/event-stream")) throw new Error("A resposta veio em um formato inesperado. Confira o histórico.");
    state.chat.conversationId = response.headers.get("X-Conversation-ID") || state.chat.conversationId;
    const runId = response.headers.get("X-Run-ID");
    await readChatStream(response, pending);
    if (version !== sessionVersion) return;
    state.chat.preview = { id: pending.id, answer: pending.answer };
    state.chat.pending = null;
    await loadChat();
    const completed = state.chat.runs.find(run => run.run_id === runId && run.outcome === "completed");
    if (completed && !pending.error && requestsPdf(pending.text)) {
      try {
        const artifact = await api(`/api/chat/runs/${runId}/artifacts`, {
          method: "POST", body: JSON.stringify({ format: "pdf" })
        });
        completed.artifacts ||= [];
        if (!completed.artifacts.some(item => item.id === artifact.id)) completed.artifacts.push(artifact);
        renderChat();
        status("PDF pronto para visualizar ou baixar.");
      } catch (error) { status(`A resposta foi salva, mas o PDF não foi criado: ${error.message}`, true); }
    }
    await loadConversations();
    if (pending.error) status(pending.error, true);
    if (!state.chat.title && state.chat.conversationId && state.chat.runs.some(run => run.outcome === "completed")) {
      try {
        const result = await api(`/api/chat/conversations/${state.chat.conversationId}/suggest-title`, { method: "POST" });
        if (result.title) { state.chat.title = result.title; renderChat(); await loadConversations(); }
      } catch { /* A conversa continua disponível para renomeação manual. */ }
    }
    if (completed && !pending.error) {
      try {
        const result = await api(`/api/chat/runs/${runId}/learn`, { method: "POST" });
        if (result.updated && $("context-dialog").open && $("context-scope").value === "profile") await loadContextNotes();
      } catch { status("A resposta foi salva, mas o perfil automático não foi atualizado.", true); }
    }
  } catch (error) {
    if (version !== sessionVersion) return;
    pending.phase = "failed";
    pending.error = error.message || "A resposta foi interrompida. Confira o histórico antes de enviar outra mensagem.";
    await loadChat();
  } finally {
    if (version === sessionVersion) { state.chat.busy = false; renderChat(); }
  }
}

function renderSelectedFiles() {
  const holder = $("chat-files");
  holder.replaceChildren();
  selectedFiles.forEach((file, index) => {
    holder.append(fileCard(file, () => { selectedFiles.splice(index, 1); renderSelectedFiles(); }));
  });
}

function audioStatus(message, error = false) {
  const note = $("chat-audio-status");
  note.textContent = message;
  note.hidden = !message;
  note.classList.toggle("error", error);
}

async function transcribeAudio(file) {
  if (audioBusy || state.chat.busy || state.screen !== "chat") return;
  if (file.size > 25_000_000) { audioStatus("O áudio deve ter até 25 MB.", true); return; }
  const version = sessionVersion;
  audioBusy = true;
  audioStatus("Transcrevendo áudio localmente…");
  renderChat();
  try {
    const response = await fetch("/api/chat/transcriptions", { method: "POST", credentials: "same-origin",
      headers: { "X-Audio-Filename": file.name, "Content-Type": file.type || "application/octet-stream" }, body: file });
    if (version !== sessionVersion) return;
    if (response.status === 401) { clearSession(); return; }
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Não foi possível transcrever o áudio.");
    const input = $("chat-text");
    input.value = [input.value.trim(), result.text].filter(Boolean).join("\n");
    input.focus();
    audioStatus("Transcrição pronta. Revise o texto antes de enviar.");
  } catch (error) {
    if (version === sessionVersion) audioStatus(error.message || "Não foi possível transcrever o áudio.", true);
  } finally {
    if (version === sessionVersion) { audioBusy = false; renderChat(); }
  }
}

function stopRecording(discard = false) {
  if (!audioRecorder) return;
  const recorder = audioRecorder;
  if (discard) recorder.onstop = null;
  clearTimeout(recordingTimer);
  if (recorder.state !== "inactive") recorder.stop();
  audioStream?.getTracks().forEach(track => track.stop());
  audioRecorder = null;
  audioStream = null;
  $("chat-record").classList.remove("recording");
  $("chat-record").setAttribute("aria-label", "Gravar áudio");
  $("chat-record").title = "Gravar áudio";
  if (discard) audioStatus("");
  if (state.screen === "chat") renderChat();
}

$("chat-audio-file").addEventListener("change", event => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) transcribeAudio(file);
});

$("chat-add-file").addEventListener("click", () => { $("chat-add-menu").open = false; $("chat-attachments").click(); });
$("chat-add-audio").addEventListener("click", () => { $("chat-add-menu").open = false; $("chat-audio-file").click(); });

$("chat-record").addEventListener("click", async () => {
  if (audioRecorder) { stopRecording(); return; }
  if (audioBusy || state.chat.busy) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    audioStatus("Este navegador não oferece gravação de áudio.", true);
    return;
  }
  const version = sessionVersion;
  audioBusy = true;
  audioStatus("Aguardando permissão para usar o microfone…");
  renderChat();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (version !== sessionVersion || state.screen !== "chat") { stream.getTracks().forEach(track => track.stop()); return; }
    const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"]
      .find(type => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.onstop = () => {
      const type = recorder.mimeType || "audio/webm";
      const extension = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      transcribeAudio(new File(chunks, `gravacao.${extension}`, { type }));
    };
    recorder.onerror = () => { stopRecording(true); audioStatus("A gravação falhou. Tente novamente.", true); };
    audioStream = stream;
    audioRecorder = recorder;
    recorder.start();
    recordingTimer = setTimeout(() => stopRecording(), 300_000);
    $("chat-record").classList.add("recording");
    $("chat-record").setAttribute("aria-label", "Parar gravação");
    $("chat-record").title = "Parar gravação";
    audioStatus("Gravando… clique no microfone para parar.");
  } catch {
    stream?.getTracks().forEach(track => track.stop());
    audioStatus("Não foi possível acessar o microfone.", true);
  } finally {
    if (version === sessionVersion) { audioBusy = false; renderChat(); }
  }
});

$("chat-attachments").addEventListener("change", event => {
  const incoming = [...event.target.files];
  const combined = [...selectedFiles, ...incoming];
  if (combined.length > 5 || combined.reduce((sum, file) => sum + file.size, 0) > 50_000_000) {
    status("Selecione até 5 arquivos, somando no máximo 50 MB.", true);
  } else { selectedFiles = combined; renderSelectedFiles(); }
  event.target.value = "";
});

$("chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (state.chat.busy || audioBusy || audioRecorder || state.chat.pending?.phase === "reconnect") return;
  const text = $("chat-text").value.trim();
  const credentialId = $("chat-credential").value;
  if (!text && !selectedFiles.length) return;
  if (!credentialId) { status("Conecte uma conta antes de enviar uma mensagem.", true); return; }
  state.chat.busy = true;
  renderChat();
  let attachments;
  try {
    attachments = await Promise.all(selectedFiles.map(file => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({ name: file.name, data: String(reader.result).split(",", 2)[1] });
      reader.onerror = () => reject(new Error(`Não foi possível ler ${file.name}.`));
      reader.readAsDataURL(file);
    })));
  } catch (error) { state.chat.busy = false; renderChat(); status(error.message, true); return; }
  state.chat.pending = { id: crypto.randomUUID(), text, attachments,
    fileCards: selectedFiles.map(file => ({ name: file.name, size: file.size })),
    credentialId, conversationId: state.chat.conversationId, projectId: state.chat.projectId,
    answer: "", phase: "sending", retried: false };
  $("chat-text").value = "";
  selectedFiles = [];
  renderSelectedFiles();
  state.chat.busy = false;
  sendChatMessage(state.chat.pending);
});
$("chat-text").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("chat-form").requestSubmit(); }
});
$("chat-more").addEventListener("click", () => { if (state.chat.before) loadChat(state.chat.before); });
$("chat-reconnect-button").addEventListener("click", () => {
  const pending = state.chat.pending;
  const credential = state.credentials.find(item => item.credential_id === pending?.credentialId);
  if (credential?.can_connect) startConnection(credential, $("chat-reconnect-button"));
  else status("Peça ao responsável pela conta que renove a conexão.", true);
});

function localDay(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
const today = new Date();
$("report-end").value = localDay(today);
today.setDate(today.getDate() - 29);
$("report-start").value = localDay(today);

function metadataRow(title, detail, runId) {
  const row = document.createElement("div");
  row.className = "metadata-row";
  const description = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = title;
  const small = document.createElement("small");
  small.textContent = detail;
  description.append(strong, small);
  row.append(description);
  if (runId) {
    const button = document.createElement("button");
    button.className = "text-button";
    button.type = "button";
    button.textContent = "Ver run";
    button.addEventListener("click", () => openRunDetail(runId));
    row.append(button);
  }
  return row;
}

function fillRows(id, rows, emptyMessage) {
  const target = $(id);
  target.replaceChildren(...rows);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = emptyMessage;
    target.append(empty);
  }
}

async function loadGovernance() {
  if (state.employee?.role !== "governance" && !state.employee?.can_govern) return;
  const start = $("report-start").value;
  const end = $("report-end").value;
  if (!start || !end || start > end) { status("Escolha um período válido.", true); return; }
  const query = `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
  try {
    const [report, runs, findings, alerts] = await Promise.all([
      api(`/api/governance/reports/daily?${query}`), api("/api/governance/runs"),
      api("/api/governance/findings"), api("/api/governance/alerts"),
    ]);
    if (state.screen !== "governance") return;
    const usage = report.usage || [];
    const categories = report.findings || [];
    const totalRuns = usage.reduce((sum, row) => sum + row.runs, 0);
    const errors = usage.reduce((sum, row) => sum + row.errors, 0);
    const latencyTotal = usage.reduce((sum, row) => sum + row.latency_ms, 0);
    const samples = usage.reduce((sum, row) => sum + row.latency_samples, 0);
    const summary = $("report-summary");
    summary.replaceChildren();
    for (const [label, value] of [["Runs", totalRuns], ["Erros", errors], ["Latência média", samples ? `${Math.round(latencyTotal / samples)} ms` : "—"], ["Achados", categories.reduce((sum, row) => sum + row.count, 0)]]) {
      const card = document.createElement("div");
      const number = document.createElement("strong");
      number.textContent = value;
      const caption = document.createElement("span");
      caption.textContent = label;
      card.append(number, caption);
      summary.append(card);
    }
    const departments = new Map();
    for (const row of usage) {
      const item = departments.get(row.department) || { runs: 0, errors: 0 };
      item.runs += row.runs;
      item.errors += row.errors;
      departments.set(row.department, item);
    }
    fillRows("usage-list", [...departments].map(([department, item]) => metadataRow(department, `${item.runs} runs · ${item.errors} erros`)), "Sem uso no período.");
    const byCategory = new Map();
    for (const row of categories) byCategory.set(row.category, (byCategory.get(row.category) || 0) + row.count);
    fillRows("categories-list", [...byCategory].map(([category, count]) => metadataRow(category, `${count} achados`)), "Sem achados no período.");
    renderGovernanceRuns(runs.runs || [], false);
    fillRows("governance-findings", (findings.findings || []).map(item => metadataRow(item.category, `${item.confidence} · ${new Date(item.created_at).toLocaleString("pt-BR")}`, item.run_id)), "Sem achados recentes.");
    fillRows("governance-alerts", (alerts.alerts || []).map(item => metadataRow(`Alerta · ${item.category}`, item.status, item.run_id)), "Sem alertas recentes.");
  } catch (error) { if (state.screen === "governance") status(error.message, true); }
}

function renderGovernanceRuns(runs, append) {
  const target = $("governance-runs");
  if (!append) target.replaceChildren();
  for (const run of runs) target.append(metadataRow(run.outcome || "Run", new Date(run.started_at).toLocaleString("pt-BR"), run.run_id));
  if (!target.children.length) fillRows("governance-runs", [], "Sem runs recentes.");
  $("runs-more").hidden = runs.length < 50;
  $("runs-more").dataset.before = runs.at(-1)?.run_id || "";
}

async function openRunDetail(runId) {
  if (state.employee?.role !== "governance" && !state.employee?.can_govern) return;
  state.runDetailId = runId;
  $("run-detail").hidden = false;
  $("run-detail-content").textContent = "Carregando detalhe…";
  $("run-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const detail = await api(`/api/governance/runs/${encodeURIComponent(runId)}`);
    if (state.runDetailId === runId && state.screen === "governance") $("run-detail-content").textContent = JSON.stringify(detail, null, 2);
  } catch (error) { if (state.runDetailId === runId) $("run-detail-content").textContent = error.message; }
}

async function downloadJson(path, filename) {
  const response = await fetch(path, { credentials: "same-origin" });
  if (response.status === 401) { clearSession(); return; }
  if (!response.ok) throw new Error("Não foi possível exportar o arquivo.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

$("report-form").addEventListener("submit", event => { event.preventDefault(); loadGovernance(); });
$("report-export").addEventListener("click", async () => {
  const start = $("report-start").value;
  const end = $("report-end").value;
  if (!start || !end || start > end) { status("Escolha um período válido.", true); return; }
  try { await downloadJson(`/api/governance/reports/daily/export?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, `governanca-${start}-${end}.json`); }
  catch (error) { status(error.message, true); }
});
$("runs-more").addEventListener("click", async () => {
  const before = $("runs-more").dataset.before;
  if (!before) return;
  try { const result = await api(`/api/governance/runs?before=${encodeURIComponent(before)}`); renderGovernanceRuns(result.runs || [], true); }
  catch (error) { status(error.message, true); }
});
$("run-detail-close").addEventListener("click", () => { state.runDetailId = null; $("run-detail-content").textContent = ""; $("run-detail").hidden = true; });
$("run-export").addEventListener("click", async () => {
  if (!state.runDetailId) return;
  try { await downloadJson(`/api/governance/runs/${encodeURIComponent(state.runDetailId)}/export`, `run-${state.runDetailId}.json`); }
  catch (error) { status(error.message, true); }
});

restore();
