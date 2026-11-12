"use strict";
/* THANOS – tela de entrada e painel de módulos (cada joia é um módulo) */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ANO = new Date().getFullYear();

/* Módulos na ordem das joias. Só o vermelho (Atendimento) existe por enquanto. */
const MODS = [
  { k: "roxa", cor: "Roxa", c: "#a24dff", c2: "#d1a8ff" },
  { k: "azul", cor: "Azul", c: "#2e8cff", c2: "#94c8ff", nome: "Petições Iniciais",
    desc: "Elaboração das petições iniciais a partir da ficha de atendimento e dos documentos do cliente." },
  { k: "vermelha", cor: "Vermelha", c: "#ff2442", c2: "#ff96a4", nome: "Atendimento",
    desc: "Ficha de atendimento do cliente, gravação e transcrição da conversa, leitura de documentos com IA, contrato e procuração." },
  { k: "laranja", cor: "Laranja", c: "#ff8a1c", c2: "#ffc48d", nome: "Processo Administrativo",
    desc: "Acompanhamento dos requerimentos e processos administrativos (INSS e outros órgãos)." },
  { k: "verde", cor: "Verde", c: "#22d36a", c2: "#93efb7", nome: "Financeiro",
    desc: "Honorários, recebimentos, repasses e despesas do escritório." },
  { k: "amarela", cor: "Amarela", c: "#ffd21a", c2: "#ffe98c", nome: "Controle de Prazos",
    desc: "Prazos processuais e administrativos, audiências e perícias, com avisos aos responsáveis." },
];

let gid = 0;
/* joia lapidada em SVG (desenho próprio) */
function gem(c, size = 72) {
  const id = "g" + (++gid);
  return `<svg class="gem" viewBox="-50 -50 100 100" width="${size}" height="${size}" aria-hidden="true">
  <defs>
    <radialGradient id="${id}b" cx="35%" cy="30%" r="80%"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".22" stop-color="${c}"/><stop offset=".8" stop-color="${c}" stop-opacity=".95"/><stop offset="1" stop-color="#000" stop-opacity=".55"/></radialGradient>
    <radialGradient id="${id}g"><stop offset="0" stop-color="${c}" stop-opacity=".75"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></radialGradient>
    <linearGradient id="${id}r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff2c9"/><stop offset=".45" stop-color="#e2b763"/><stop offset="1" stop-color="#8a6322"/></linearGradient>
  </defs>
  <circle r="48" fill="url(#${id}g)" class="pulse"/>
  <ellipse rx="27" ry="33" fill="none" stroke="url(#${id}r)" stroke-width="5"/>
  <ellipse rx="24" ry="30" fill="url(#${id}b)"/>
  <g fill="#fff" stroke="#fff" stroke-opacity=".25" stroke-width=".6">
    <polygon points="0,-30 -12,-14 0,-8 12,-14" fill-opacity=".28"/>
    <polygon points="-24,0 -12,-14 0,-8 -10,6" fill-opacity=".12"/>
    <polygon points="24,0 12,-14 0,-8 10,6" fill-opacity=".05"/>
    <polygon points="0,30 -10,6 0,-8 10,6" fill-opacity=".08"/>
    <polygon points="-24,0 -10,6 0,30 -16,22" fill-opacity=".02"/>
  </g>
  <ellipse cx="-8" cy="-16" rx="5" ry="3" fill="#fff" opacity=".8" transform="rotate(-30 -8 -16)"/>
</svg>`;
}

/* emblema da tela de entrada: anel dourado com as seis joias e a balança da justiça */
function emblem() {
  const R = 175, cx = 260, cy = 260;
  const pts = MODS.map((m, i) => { const a = (-90 + i * 60) * Math.PI / 180; return [cx + R * Math.cos(a), cy + R * Math.sin(a), m]; });
  const gems = pts.map(([x, y, m]) => `<g transform="translate(${x - 38} ${y - 38})"><title>Joia ${m.cor}${m.nome ? " – " + m.nome : ""}</title>${gem(m.c, 76)}</g>`).join("");
  const hex = pts.map(([x, y]) => `${x},${y}`).join(" ");
  return `<svg viewBox="0 0 520 520" role="img" aria-label="Emblema THANOS: seis joias em volta da balança da justiça">
  <defs>
    <linearGradient id="au" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff2c9"/><stop offset=".4" stop-color="#e2b763"/><stop offset="1" stop-color="#8a6322"/></linearGradient>
    <radialGradient id="halo"><stop offset="0" stop-color="#e2b763" stop-opacity=".35"/><stop offset=".6" stop-color="#e2b763" stop-opacity=".06"/><stop offset="1" stop-color="#e2b763" stop-opacity="0"/></radialGradient>
  </defs>
  <circle cx="260" cy="260" r="250" fill="url(#halo)"/>
  <g class="spin" fill="none" stroke="#e2b763" stroke-opacity=".45">
    <circle cx="260" cy="260" r="236" stroke-width="1"/>
    <circle cx="260" cy="260" r="222" stroke-width=".6" stroke-dasharray="2 6"/>
    <polygon points="260,8 512,260 260,512 8,260" stroke-width=".8"/>
    <polygon points="82,82 438,82 438,438 82,438" stroke-width=".5" stroke-opacity=".3"/>
  </g>
  <polygon points="${hex}" fill="none" stroke="url(#au)" stroke-width="2" stroke-opacity=".7"/>
  <circle cx="260" cy="260" r="${R}" fill="none" stroke="url(#au)" stroke-width="6"/>
  <circle cx="260" cy="260" r="${R - 9}" fill="none" stroke="#e2b763" stroke-opacity=".4" stroke-width="1"/>
  <circle cx="260" cy="260" r="92" fill="#0d1a3a" stroke="url(#au)" stroke-width="5"/>
  <circle cx="260" cy="260" r="82" fill="none" stroke="#e2b763" stroke-opacity=".35"/>
  <g fill="none" stroke="url(#au)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M260 205v105M232 318h56M244 310h32"/>
    <path d="M214 228h92"/>
    <circle cx="260" cy="203" r="6" fill="url(#au)"/>
    <path d="M222 230l-20 40M222 230l20 40M298 230l-20 40M298 230l20 40" stroke-width="3"/>
    <path d="M196 270q26 22 52 0z M272 270q26 22 52 0z" fill="url(#au)" stroke-width="2"/>
  </g>
  ${gems}
</svg>`;
}

const ICON_USER = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>`;
const ICON_LOCK = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/><circle cx="12" cy="15.5" r="1.3" fill="currentColor"/></svg>`;

/* ---------------- entrada ---------------- */
function nextUrl() { const n = new URLSearchParams(location.search).get("next"); return n && /^\/[a-z]/i.test(n) && !n.startsWith("//") ? n : null; }

function showLogin(msg, info) {
  document.title = "THANOS – Entrar";
  $("#app").innerHTML = `<main class="login">
  <div class="lcol">
    <h1 class="logo gold">THANOS</h1>
    <form class="box" id="loginF" autocomplete="on" novalidate>
      ${msg ? `<div class="msg" role="alert">${esc(msg)}</div>` : ""}
      ${info ? `<div class="msg info" role="status">${esc(info)}</div>` : ""}
      <label class="fld">${ICON_USER}
        <input type="text" id="lEmail" name="username" placeholder="Usuário" aria-label="Usuário (e-mail)" autocomplete="username" autocapitalize="none" spellcheck="false" required></label>
      <label class="fld">${ICON_LOCK}
        <input type="password" id="lPw" name="password" placeholder="senha" aria-label="Senha" autocomplete="current-password" required>
        <button type="button" class="forgot" id="forgot">Esqueceu a senha?</button></label>
      <button class="enter" id="enter">ENTRAR</button>
      <p class="motto">Gestão jurídica em suas mãos</p>
    </form>
    <div class="foot"><span class="logo gold">THANOS</span><small>© ${ANO} THANOS Sistemas Jurídicos</small></div>
  </div>
  <div class="emblem">${emblem()}</div>
</main>`;
  const u = $("#lEmail"); if (showLogin.last) u.value = showLogin.last;
  (u.value ? $("#lPw") : u).focus();
  $("#forgot").onclick = () => { showLogin.last = u.value; showLogin(null, "Para trocar a senha, fale com o administrador do sistema no escritório."); };
  $("#loginF").onsubmit = async e => {
    e.preventDefault();
    const email = u.value.trim(), password = $("#lPw").value;
    showLogin.last = email;
    if (!email || !password) return showLogin("Informe usuário e senha.");
    $("#enter").disabled = true; $("#enter").textContent = "ENTRANDO…";
    try {
      const r = await fetch("/api/login", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
      if (!r.ok) return showLogin(r.status === 401 ? "Usuário ou senha inválidos." : "Não foi possível entrar agora. Tente de novo.");
      const n = nextUrl(); if (n) { location.href = n; return; }
      await boot();
    } catch (_) { showLogin("Sem conexão com o servidor."); }
  };
}

/* ---------------- painel ---------------- */
let CSRF = "";
async function boot() {
  let m;
  try { const r = await fetch("/api/me", { credentials: "same-origin" }); if (!r.ok) throw 0; m = await r.json(); }
  catch (_) { return showLogin(); }
  const n = nextUrl(); if (n) { location.href = n; return; }
  history.replaceState(null, "", "/");
  CSRF = m.csrf; const U = m.user, P = U.perms || {};
  document.title = "THANOS – Painel";
  const card = x => {
    if (x.k !== "vermelha") return `<article class="mod off" style="--c:${x.c};--c2:${x.c2}">${gem(x.c)}<div>
      <span class="tag">Joia ${x.cor}</span><h2>${x.nome || "Módulo " + x.cor.toLowerCase()}</h2><p>${x.desc || "Reservado para um próximo módulo do THANOS."}</p><span class="soon">Em breve</span></div></article>`;
    const acts = [P.fichas_ver && `<a class="btn" href="/ficha/">Fichas de atendimento</a>`, P.gravacao && `<a class="btn" href="/atendimento">Gravação com IA</a>`].filter(Boolean);
    return `<article class="mod on" style="--c:${x.c};--c2:${x.c2}">${gem(x.c)}<div>
      <span class="tag">Joia ${x.cor}</span><h2>${x.nome}</h2><p>${x.desc}</p>
      <div class="acts">${acts.join("") || `<span class="soon">Seu usuário ainda não tem acesso. Peça ao administrador.</span>`}</div></div></article>`;
  };
  $("#app").innerHTML = `<header class="top"><span class="logo gold">THANOS</span>
    <div class="who">${U.role === "admin" ? `<a class="btn" href="/usuarios">Usuários</a>` : ""}<span>${esc(U.name)}</span><button class="btn" id="sair">Sair</button></div></header>
  <main class="wrap"><p class="hello">Olá, ${esc(String(U.name || "").split(" ")[0])}.</p><p class="sub">Escolha um módulo. Cada joia é uma parte do sistema.</p>
  <div class="grid">${MODS.map(card).join("")}</div>
  <div class="foot" style="margin-top:40px"><small>© ${ANO} THANOS Sistemas Jurídicos · Buss &amp; Hackbarth Advogados</small></div></main>`;
  $("#sair").onclick = async () => {
    await fetch("/api/logout", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": CSRF } }).catch(() => {});
    showLogin.last = ""; showLogin();
  };
}

/* ---------------- céu estrelado ---------------- */
(function stars() {
  const cv = $("#stars"), cx = cv.getContext("2d"); let S = [];
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  function size() {
    const d = devicePixelRatio || 1; cv.width = innerWidth * d; cv.height = innerHeight * d; cx.setTransform(d, 0, 0, d, 0, 0);
    const n = Math.round(innerWidth * innerHeight / 2600);
    S = Array.from({ length: n }, () => ({ x: Math.random() * innerWidth, y: Math.random() * innerHeight, r: Math.random() ** 3 * 1.6 + .25,
      a: Math.random() * .7 + .2, t: Math.random() * 6.28, w: Math.random() * .02 + .004, g: Math.random() < .12 }));
    if (still || !size.on) { size.on = true; draw(); }
  }
  function draw() {
    cx.clearRect(0, 0, innerWidth, innerHeight);
    for (const s of S) {
      const a = still ? s.a : s.a * (.6 + .4 * Math.sin(s.t += s.w));
      cx.globalAlpha = a; cx.fillStyle = s.g ? "#f3d798" : "#dfe8ff";
      cx.beginPath(); cx.arc(s.x, s.y, s.r, 0, 6.283); cx.fill();
    }
    if (!still) requestAnimationFrame(draw);
  }
  addEventListener("resize", () => { clearTimeout(size.t); size.t = setTimeout(size, 150); });
  size();
})();

boot();
