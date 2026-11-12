"use strict";
/* Tela de usuários: só o administrador. Cadastra, bloqueia, troca senha e define o que cada pessoa acessa. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PAPEL = { admin: "Administrador", advogado: "Advogado(a)", assistente: "Assistente/estagiário(a)" };
let CSRF = "", ME = null, CAT = null, USERS = [];

function toast(m) { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3500); }
async function api(path, opt = {}) {
  const o = Object.assign({ credentials: "same-origin", headers: {} }, opt);
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
  if (o.method && o.method !== "GET") o.headers["X-CSRF-Token"] = CSRF;
  const r = await fetch(path, o);
  if (r.status === 401) { location.href = "/?next=/usuarios"; throw new Error("login"); }
  const b = (r.headers.get("content-type") || "").includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((b && b.detail) || `Erro ${r.status}`);
  return b;
}

function permBoxes(prefix, perms, disabled) {
  return `<div class="perms">${CAT.perms.map(p => `<label><input type="checkbox" data-p="${p.key}" id="${prefix}_${p.key}" ${perms[p.key] ? "checked" : ""} ${disabled ? "disabled" : ""}>
    <span>${esc(p.label)}<small>${esc(p.help)}</small></span></label>`).join("")}</div>`;
}
const readPerms = root => Object.fromEntries([...root.querySelectorAll("input[data-p]")].map(i => [i.dataset.p, i.checked]));
const roleSel = (id, v) => `<select id="${id}">${CAT.roles.map(r => `<option value="${r}" ${r === v ? "selected" : ""}>${PAPEL[r]}</option>`).join("")}</select>`;

function render() {
  $("#view").innerHTML = `
  <section class="card"><h2>Novo usuário</h2>
    <form id="nf"><div class="nf">
      <label>Nome<input id="n_name" type="text" required></label>
      <label>E-mail (é o login)<input id="n_email" type="email" required autocomplete="off"></label>
      <label>Papel${roleSel("n_role", "advogado")}</label>
      <label>Senha inicial (mín. 10)<input id="n_pw" type="password" minlength="10" required autocomplete="new-password"></label>
    </div>
    <p class="muted">Permissões (já vêm com o padrão do papel; ajuste se quiser):</p>
    <div id="n_perms">${permBoxes("n", CAT.defaults.advogado, false)}</div>
    <button class="btn pri">Cadastrar</button></form>
  </section>
  <h2>Usuários (${USERS.length})</h2>
  <div class="ulist">${USERS.map(card).join("")}</div>`;
  $("#n_role").onchange = () => { $("#n_perms").innerHTML = permBoxes("n", CAT.defaults[$("#n_role").value], $("#n_role").value === "admin"); };
  $("#nf").onsubmit = async e => { e.preventDefault();
    try {
      await api("/api/admin/users", { method: "POST", json: { name: $("#n_name").value, email: $("#n_email").value, role: $("#n_role").value,
        password: $("#n_pw").value, perms: $("#n_role").value === "admin" ? null : readPerms($("#n_perms")) } });
      toast("Usuário cadastrado"); await load();
    } catch (err) { toast(err.message); } };
  document.querySelectorAll("[data-act]").forEach(b => b.onclick = () => act(b.dataset.act, b.dataset.id));
  document.querySelectorAll("select[data-role]").forEach(s => s.onchange = () => {
    const box = document.querySelector(`#c_${s.dataset.role} .permbox`);
    box.innerHTML = permBoxes("u" + s.dataset.role, CAT.defaults[s.value], s.value === "admin"); });
}

function card(u) {
  const self = ME && u.id === ME.id;
  return `<section class="card" id="c_${u.id}">
    <div class="uhead"><h3>${esc(u.name)}${self ? '<span class="tag">você</span>' : ""}${u.active ? "" : '<span class="tag off">bloqueado</span>'}</h3>
      <span class="muted">${esc(u.email)}</span></div>
    <div class="nf"><label>Nome<input type="text" id="nm_${u.id}" value="${esc(u.name)}"></label>
      <label>Papel<select data-role="${u.id}" id="r_${u.id}">${CAT.roles.map(r => `<option value="${r}" ${r === u.role ? "selected" : ""}>${PAPEL[r]}</option>`).join("")}</select></label></div>
    <p class="muted">${u.role === "admin" ? "O administrador sempre pode tudo." : u.custom ? "Permissões ajustadas para esta pessoa." : "Usando o padrão do papel."}</p>
    <div class="permbox">${permBoxes("u" + u.id, u.perms, u.role === "admin")}</div>
    <div class="acts">
      <button class="btn pri" data-act="salvar" data-id="${u.id}">Salvar</button>
      ${u.role !== "admin" && u.custom ? `<button class="btn" data-act="padrao" data-id="${u.id}">Voltar ao padrão do papel</button>` : ""}
      <button class="btn" data-act="senha" data-id="${u.id}">Definir nova senha</button>
      ${self ? "" : `<button class="btn ${u.active ? "danger" : ""}" data-act="${u.active ? "bloquear" : "desbloquear"}" data-id="${u.id}">${u.active ? "Bloquear acesso" : "Desbloquear"}</button>`}
    </div></section>`;
}

async function act(a, id) {
  const c = $("#c_" + id);
  try {
    if (a === "salvar") {
      const role = $("#r_" + id).value;
      await api(`/api/admin/users/${id}`, { method: "PATCH", json: { name: $("#nm_" + id).value, role, perms: role === "admin" ? null : readPerms(c), reset_perms: role === "admin" } });
      toast("Salvo. Vale a partir do próximo clique da pessoa.");
    } else if (a === "padrao") {
      await api(`/api/admin/users/${id}`, { method: "PATCH", json: { reset_perms: true } }); toast("Voltou ao padrão do papel");
    } else if (a === "senha") {
      const pw = prompt("Nova senha (mínimo 10 caracteres). A pessoa será desconectada e entra com a nova senha:");
      if (!pw) return;
      await api(`/api/admin/users/${id}/password`, { method: "POST", json: { password: pw } }); toast("Senha alterada");
    } else if (a === "bloquear" || a === "desbloquear") {
      if (a === "bloquear" && !confirm("Bloquear este usuário? Ele sai na hora de todos os aparelhos.")) return;
      await api(`/api/admin/users/${id}`, { method: "PATCH", json: { active: a === "desbloquear" } }); toast(a === "bloquear" ? "Usuário bloqueado" : "Usuário desbloqueado");
    }
    await load();
  } catch (err) { toast(err.message); }
}

async function load() { USERS = await api("/api/admin/users"); render(); }
(async () => {
  try {
    const m = await api("/api/me"); ME = m.user; CSRF = m.csrf;
    if (ME.role !== "admin") { $("#view").innerHTML = `<div class="card"><h2>Somente o administrador</h2><p>Esta tela é restrita ao administrador do sistema.</p></div>`; return; }
    CAT = await api("/api/admin/permissions"); await load();
  } catch (e) { if (e.message !== "login") $("#view").innerHTML = `<div class="card">${esc(e.message)}</div>`; }
})();
