"use strict";
/* Atendimentos com IA – frontend (sem chaves de API; tudo passa pelo backend autenticado) */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDT = s => s ? new Date(s).toLocaleString("pt-BR") : "";
const fmtSize = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
let ME = null, CSRF = "", LIM = {}, ATT = null, POLL = null;

function toast(m) { const t = $("#toast"); t.textContent = m; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3500); }

async function api(path, opt = {}) {
  const o = Object.assign({ credentials: "same-origin", headers: {} }, opt);
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
  if (o.method && o.method !== "GET") o.headers["X-CSRF-Token"] = CSRF;
  const r = await fetch(path, o);
  if (r.status === 401) { showLogin(); throw new Error("Sessão expirada"); }
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((body && body.detail) || `Erro ${r.status}`);
  return body;
}

/* ---------------- login e navegação ---------------- */
function showLogin(msg) {
  $("#who").innerHTML = "";
  $("#view").innerHTML = `<form class="card" id="loginF" style="max-width:380px;margin:40px auto"><h2>Entrar</h2>${msg ? `<div class="al bad">${esc(msg)}</div>` : ""}
  <label>E-mail<input type="email" id="lEmail" required autocomplete="username"></label>
  <label>Senha<input type="password" id="lPw" required autocomplete="current-password"></label><button class="btn pri">Entrar</button></form>`;
  $("#loginF").onsubmit = async e => { e.preventDefault();
    try { const r = await fetch("/api/login", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: $("#lEmail").value, password: $("#lPw").value }) });
      if (!r.ok) return showLogin("E-mail ou senha inválidos"); if (goNext()) return; await boot(); } catch (_) { showLogin("Não foi possível entrar"); } };
}
function goNext() { const n = new URLSearchParams(location.search).get("next"); if (n && /^\/[a-z]/i.test(n)) { location.href = n; return true; } return false; }
async function boot() {
  try { const m = await api("/api/me"); ME = m.user; CSRF = m.csrf; LIM = m.limits; }
  catch (_) { return showLogin(); }
  if (goNext()) return;
  const P = ME.perms || {};
  $("#who").innerHTML = `${P.fichas_ver ? `<a class="btn" href="/ficha/">Fichas de atendimento</a>` : ""}${ME.role === "admin" ? `<a class="btn" href="/usuarios">Usuários</a>` : ""}<span>${esc(ME.name)}</span><button class="btn" id="sair">Sair</button>`;
  $("#sair").onclick = async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); showLogin(); };
  if (!P.gravacao) {
    if (P.fichas_ver) { location.href = "/ficha/"; return; }
    $("#view").innerHTML = `<div class="card"><h2>Sem acesso</h2><p>Seu usuário ainda não tem permissões. Peça ao administrador.</p></div>`; return;
  }
  window.onhashchange = route; route();
}
function route() {
  stopPoll();
  const h = location.hash.slice(1);
  if (h.startsWith("att-")) return openAttendance(h.slice(4));
  if (h.startsWith("cli-")) return openClient(h.slice(4));
  return listClients();
}

async function listClients() {
  $("#view").innerHTML = `<section class="card"><h2>Clientes</h2><div class="row"><input type="text" id="q" class="grow" placeholder="Buscar por nome ou CPF"><button class="btn" id="novoCli">+ Cliente</button></div><div id="cl" class="list"></div></section>`;
  const load = async () => { const q = $("#q"); if (!q) return; const L = await api("/api/clients?q=" + encodeURIComponent(q.value)); if (!$("#cl")) return;
    $("#cl").innerHTML = L.length ? L.map(c => `<a href="#cli-${c.id}">${esc(c.name)} <span class="note">${esc(c.cpf || "")}</span></a>`).join("") : `<p class="note">Nenhum cliente.</p>`; };
  $("#q").oninput = () => { clearTimeout(load.t); load.t = setTimeout(load, 250); };
  $("#novoCli").onclick = async () => { const n = $("#q").value.trim(); if (!n) return toast("Digite o nome do cliente no campo de busca e clique em + Cliente");
    const c = await api("/api/clients", { method: "POST", json: { name: n } }); location.hash = "cli-" + c.id; };
  load();
}

async function openClient(cid) {
  let L;
  try { L = await api(`/api/clients/${cid}/attendances`); } catch (e) { $("#view").innerHTML = `<div class="al bad">${esc(e.message)}</div>`; return; }
  $("#view").innerHTML = `<p><a href="#">← Clientes</a></p><section class="card"><h2>Atendimentos com IA</h2>
   <div class="row"><button class="btn pri" id="novoAt">Novo atendimento</button></div>
   <div class="list">${L.map(a => `<a href="#att-${a.id}">${fmtDT(a.created_at)} · <span class="chip">${esc(a.status)}</span> <span class="note">áudio: ${esc(a.audio_status)}</span></a>`).join("") || `<p class="note">Nenhum atendimento.</p>`}</div></section>`;
  $("#novoAt").onclick = async () => { const a = await api(`/api/clients/${cid}/attendances`, { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() } }); location.hash = "att-" + a.id; };
}

/* ---------------- atendimento ---------------- */
const STATUS_TXT = { draft: "Rascunho", recording: "Gravando", uploading: "Enviando", transcribing: "Transcrevendo", analyzing_documents: "Analisando documentos",
  generating_summary: "Gerando ficha", awaiting_review: "Aguardando revisão", finalized: "Finalizado", failed: "Falhou" };
const AUDIO_TXT = { none: "Sem áudio", stored: "Áudio guardado temporariamente", audio_deletion_pending: "Exclusão do áudio pendente (nova tentativa automática)", deleted: "Áudio excluído", expired: "Áudio excluído por prazo" };
const BUSY = ["transcribing", "analyzing_documents", "generating_summary", "uploading"];

async function openAttendance(id) {
  try { ATT = await api(`/api/attendances/${id}`); } catch (e) { $("#view").innerHTML = `<p><a href="#">← Clientes</a></p><div class="al bad">${esc(e.message)}</div>`; return; }
  render();
}
function stopPoll() { clearTimeout(POLL); POLL = null; }
function schedulePoll() { stopPoll(); if (ATT && (BUSY.includes(ATT.status) || ATT.jobs.some(j => j.status === "queued" || j.status === "running"))) POLL = setTimeout(async () => { if (REC.state !== "idle") return schedulePoll(); ATT = await api(`/api/attendances/${ATT.id}`).catch(() => ATT); render(true); }, 3000); }

function render(keepScroll) {
  const a = ATT, fin = a.status === "finalized", y = scrollY;
  const st = a.status === "failed" ? "bad" : fin ? "ok" : BUSY.includes(a.status) ? "warn" : "acc";
  $("#view").innerHTML = `
  <p><a href="#cli-${a.client_id}">← Atendimentos do cliente</a></p>
  <section class="card"><div class="row"><h2 class="grow">Atendimento de ${fmtDT(a.created_at)}</h2><span class="chip ${st}">${STATUS_TXT[a.status] || a.status}</span>
    <span class="chip ${a.audio.status === "audio_deletion_pending" ? "bad" : a.audio.status === "deleted" ? "ok" : ""}">${AUDIO_TXT[a.audio.status]}</span></div>
    <div class="note">Responsável: ${esc(a.responsible)} · versão ${a.version}${a.finalized_at ? ` · finalizado por ${esc(a.finalized_by)} em ${fmtDT(a.finalized_at)}` : ""}${a.audio.deleted_at ? ` · áudio excluído em ${fmtDT(a.audio.deleted_at)}` : ""}</div>
    ${a.status === "failed" ? `<div class="al bad">Falha na etapa <b>${esc(a.failed_step)}</b>: ${esc(a.last_error)}. As etapas concluídas foram preservadas. <button class="btn" data-a="retry">Tentar de novo</button></div>` : ""}
  </section>
  ${fin ? "" : consentHTML(a) + recorderHTML(a)}
  ${docsHTML(a, fin)}
  <section class="card"><h2>Anotações do atendimento</h2><textarea id="notes" ${fin ? "disabled" : ""} placeholder="Anotações do advogado (também usadas para gerar a ficha sem áudio)">${esc(a.notes)}</textarea></section>
  ${transcriptHTML(a, fin)}
  ${actionsHTML(a, fin)}
  ${fichaHTML(a, fin)}`;
  bind();
  if (keepScroll) scrollTo(0, y);
  schedulePoll();
}

function consentHTML(a) {
  return `<section class="card"><h2>Ciência e autorização do cliente</h2>
  <label class="row"><input type="checkbox" id="consent" ${a.consent.given ? "checked" : ""}> <span class="grow">O cliente foi informado e <b>autorizou</b> a gravação deste atendimento, a transcrição do áudio e a análise do áudio e dos documentos por inteligência artificial (OpenAI). Foi informado também de que o áudio será excluído após a transcrição e a finalização da ficha.</span></label>
  ${a.consent.given ? `<div class="note">Registrado por ${esc(a.consent.by)} em ${fmtDT(a.consent.at)} (texto ${esc(a.consent.version)}).</div>` : ""}</section>`;
}
function recorderHTML(a) {
  return `<section class="card"><h2>Gravação</h2>
  <div class="note">Para atendimento presencial: o microfone deste computador não captura o áudio de quem está do outro lado de uma videoconferência.</div>
  <div class="row"><label class="grow">Microfone <select id="mic"><option value="">Padrão do sistema</option></select></label></div>
  <div class="rec"><span class="dot" id="dot"></span><span class="timer" id="timer">00:00</span><canvas class="level" id="level" width="160" height="24" aria-hidden="true"></canvas>
    <button class="btn pri" id="bStart">Iniciar</button><button class="btn" id="bPause" disabled>Pausar</button><button class="btn" id="bResume" disabled>Retomar</button><button class="btn danger" id="bStop" disabled>Encerrar</button></div>
  <div id="recMsg"></div>
  <div class="note">Gravado até agora: ${Math.round(a.recording_seconds / 60)} min em ${a.audio.segments.length} parte(s)${a.audio.segments.length ? " – " + a.audio.segments.map(s => `parte ${s.seq + 1}: ${s.status === "transcribed" ? "transcrita" : s.status}`).join(", ") : ""}. Limite: ${LIM.max_recording_minutes} min. Áudio de rascunho é excluído automaticamente após ${LIM.temp_audio_ttl_hours} h.</div></section>`;
}
function docsHTML(a, fin) {
  return `<section class="card"><h2>Documentos</h2>
  ${fin ? "" : `<div class="drop" id="drop">Arraste aqui PDF, JPG ou PNG (CNIS, laudos, exames, relatórios, cartas do INSS) ou <button class="btn" id="bAttach">Anexar documentos</button><input type="file" id="fAttach" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" multiple hidden></div>
  <div class="note">Até ${LIM.max_attachments} arquivos de ${LIM.max_attachment_mb} MB cada.</div>`}
  <div class="tbl"><table><thead><tr><th>Arquivo</th><th>Tipo</th><th>Tamanho</th><th>Status</th><th></th></tr></thead><tbody>
  ${a.documents.map(d => `<tr><td><a href="/api/attendances/${a.id}/documents/${d.id}/file" target="_blank" rel="noopener">${esc(d.name)}</a></td><td>${esc(d.type)}</td><td class="mono">${fmtSize(d.size)}${d.pages ? ` · ${d.pages} pág.` : ""}</td>
   <td><span class="chip ${d.status === "extracted" ? "ok" : d.status === "failed" ? "bad" : d.status === "partial" ? "warn" : ""}">${esc({ uploaded: "aguardando análise", extracting: "analisando", extracted: "analisado", partial: "análise parcial", failed: "falhou" }[d.status] || d.status)}</span>${d.problem ? `<div class="note">${esc(d.problem)}</div>` : ""}${d.pages_visual ? `<div class="note">${d.pages_visual} página(s) digitalizada(s) – análise visual</div>` : ""}</td>
   <td>${fin ? "" : `<button class="btn danger" data-rm="${d.id}">Remover</button>`}</td></tr>`).join("") || `<tr><td colspan="5" class="note">Nenhum documento.</td></tr>`}
  </tbody></table></div></section>`;
}
function transcriptHTML(a, fin) {
  const t = a.transcript;
  if (!t.original) return `<section class="card"><h2>Transcrição</h2><p class="note">${a.audio.segments.length ? "Clique em Transcrever para gerar a transcrição." : "Sem gravação. É possível gerar a ficha só com documentos e anotações."}</p></section>`;
  return `<section class="card"><h2>Transcrição</h2><div class="note">Modelo: ${esc(t.model)} · concluída em ${fmtDT(t.completed_at)}. Sem identificação automática de quem fala.</div>
  <details><summary>Transcrição original (somente leitura)</summary><pre style="white-space:pre-wrap">${esc(t.original)}</pre></details>
  <label>Transcrição revisada (usada para gerar a ficha)<textarea id="trRev" style="min-height:180px" ${fin ? "disabled" : ""}>${esc(t.revised ?? t.original)}</textarea></label>
  <div class="row"><button class="btn" data-a="copytr">Copiar transcrição</button><button class="btn" data-a="dltr">Baixar transcrição (.txt)</button><span class="note">Para anexar na ficha de atendimento.</span></div>
  <details><summary>Segmentos usados nas referências (T001…)</summary>${t.segments.map(([id, s]) => `<div class="seg"><b>${id}</b><span>${esc(s)}</span></div>`).join("")}</details></section>`;
}
function actionsHTML(a, fin) {
  if (fin) return "";
  const busy = BUSY.includes(a.status);
  return `<section class="card"><div class="row">
   <button class="btn" data-a="transcribe" ${busy || !a.audio.segments.length ? "disabled" : ""}>Transcrever</button>
   <button class="btn" data-a="analyze" ${busy || !a.documents.some(d => d.status === "uploaded" || d.status === "failed") ? "disabled" : ""}>Analisar documentos</button>
   <button class="btn" data-a="generate" ${busy ? "disabled" : ""}>Gerar ficha</button>
   <span class="grow"></span><button class="btn" data-a="save">Salvar rascunho</button><button class="btn pri" data-a="finalize" ${!a.ficha_revisada || busy ? "disabled" : ""}>Finalizar</button></div>
   ${a.jobs.filter(j => j.status !== "done").map(j => `<div class="note">${esc(j.kind)}: ${esc(j.status)}${j.attempts ? ` (tentativa ${j.attempts})` : ""}${j.error ? " – " + esc(j.error) : ""}</div>`).join("")}</section>`;
}

/* ---------------- ficha ---------------- */
const SECOES = [["motivo_consulta", "Motivo da consulta"], ["objetivo_cliente", "Objetivo do cliente"], ["relato_cronologico", "Relato do cliente (cronológico)"],
  ["datas_relevantes", "Datas relevantes"], ["beneficios_requerimentos_processos", "Benefícios, requerimentos e processos"], ["documentos_analisados", "Documentos analisados"],
  ["informacoes_documentadas", "Informações documentadas"], ["orientacoes_advogado", "Orientações do advogado"], ["divergencias", "Divergências"],
  ["documentos_pendentes", "Documentos pendentes"], ["providencias_discutidas", "Providências discutidas"], ["prazos_mencionados", "Prazos mencionados"],
  ["pontos_para_confirmacao", "Pontos para confirmação"], ["informacoes_ausentes", "Informações ausentes"]];
const LABELS = { data: "Data", descricao: "Descrição", evento: "Evento", tipo: "Tipo", numero: "NB / nº", der: "DER", dib: "DIB", situacao: "Situação", motivo_decisao: "Motivo da decisão",
  document_id: "Documento", tipo_documento: "Tipo", cobertura: "Cobertura", observacao: "Observação", categoria: "Categoria", valor_original: "Valor original", assunto: "Assunto",
  versao_cliente: "Versão do cliente", versao_documento: "Versão do documento", documento: "Documento", motivo: "Motivo", responsavel: "Responsável", ponto: "Ponto" };
function docName(id) { const d = ATT.documents.find(x => x.id === id); return d ? d.name : id; }
function fontesHTML(fs) { return fs && fs.length ? `<div class="src">${fs.map(f => `<span title="${esc(f.trecho || "")}">${f.tipo === "documento" ? esc(docName(f.document_id)) + (f.pagina ? ` p.${f.pagina}` : "") : f.tipo === "transcricao" ? esc(f.segmento) : "anotação"}</span>`).join("")}</div>` : `<div class="src"><span>sem fonte</span></div>`; }
function fichaHTML(a, fin) {
  const ai = a.ai_latest, f = fin ? a.ficha_final : a.ficha_revisada;
  if (!f) return ai ? "" : "";
  const newer = ai && !ai.is_base_of_revision;
  return `<section class="card"><h2>${fin ? "Ficha final" : "Ficha para revisão do advogado"}</h2>
  ${ai ? `<div class="note">Resultado da IA: ${esc(ai.model)} em ${fmtDT(ai.created_at)} · ${a.ai_runs.length} versão(ões) geradas. Revise tudo antes de finalizar; a IA não substitui a análise jurídica.</div>` : ""}
  ${ai && ai.warnings && ai.warnings.length ? `<div class="al">Referências inválidas removidas pelo servidor: ${esc(ai.warnings.join("; "))}</div>` : ""}
  ${newer && !fin ? `<div class="al">Há uma versão mais nova da IA. Sua ficha revisada não foi alterada; use "Trazer da IA" em cada seção para substituir somente o que quiser.</div>` : ""}
  ${ai && ai.calculos && ai.calculos.cnis ? `<div class="al ok"><b>Cálculo determinístico (vínculos do CNIS):</b> ${esc(ai.calculos.cnis.total_aproximado)} (${ai.calculos.cnis.total_dias} dias). Método: ${esc(ai.calculos.cnis.metodo)}.${ai.calculos.cnis.sobreposicoes.length ? ` Sobreposições: ${esc(ai.calculos.cnis.sobreposicoes.map(o => o.vinculo + " de " + o.inicio + " a " + o.sobrepoe_ate).join("; "))}.` : ""}${ai.calculos.cnis.vinculos_sem_datas.length ? ` Sem datas completas: ${esc(ai.calculos.cnis.vinculos_sem_datas.join(", "))}.` : ""}</div>` : ""}
  ${SECOES.map(([k, l]) => secaoHTML(k, l, f[k], fin, newer && ai ? ai.ficha[k] : undefined)).join("")}</section>`;
}
function secaoHTML(k, l, v, fin, aiV) {
  const head = `<header><h3>${l}</h3>${aiV !== undefined && !fin && JSON.stringify(aiV) !== JSON.stringify(v) ? `<button class="btn" data-pull="${k}">Trazer da IA</button>` : ""}</header>`;
  if (typeof v === "string") return `<div class="fsec">${head}<textarea data-fk="${k}" ${fin ? "disabled" : ""}>${esc(v)}</textarea></div>`;
  if (k === "informacoes_ausentes") return `<div class="fsec">${head}${v.map((s, i) => `<div class="row"><input type="text" class="grow" data-fk="${k}" data-i="${i}" value="${esc(s)}" ${fin ? "disabled" : ""}>${fin ? "" : `<button class="btn danger" data-del="${k}" data-i="${i}">×</button>`}</div>`).join("") || `<p class="note">Nenhum item.</p>`}${fin ? "" : `<button class="btn" data-add="${k}">+ Item</button>`}</div>`;
  return `<div class="fsec">${head}${v.map((it, i) => `<div class="item">${Object.keys(it).filter(p => p !== "fontes").map(p => `<label>${LABELS[p] || p}${p === "document_id" ? `<input type="text" value="${esc(docName(it[p]))}" disabled>` : `<input type="text" data-fk="${k}" data-i="${i}" data-p="${p}" value="${esc(it[p] ?? "")}" ${fin ? "disabled" : ""}>`}</label>`).join("")}${it.fontes ? fontesHTML(it.fontes) : ""}${fin ? "" : `<div><button class="btn danger" data-del="${k}" data-i="${i}">Remover item</button></div>`}</div>`).join("") || `<p class="note">Nenhum item.</p>`}${fin ? "" : `<button class="btn" data-add="${k}">+ Item</button>`}</div>`;
}
const EMPTY_ITEM = { relato_cronologico: { data: null, descricao: "", fontes: [] }, datas_relevantes: { data: "", evento: "", fontes: [] },
  beneficios_requerimentos_processos: { tipo: "", numero: null, der: null, dib: null, situacao: null, motivo_decisao: null, fontes: [] },
  informacoes_documentadas: { categoria: "", descricao: "", valor_original: null, fontes: [] }, orientacoes_advogado: { descricao: "", fontes: [] },
  divergencias: { assunto: "", versao_cliente: "", versao_documento: "", fontes: [] }, documentos_pendentes: { documento: "", motivo: null, fontes: [] },
  providencias_discutidas: { descricao: "", responsavel: null, fontes: [] }, prazos_mencionados: { descricao: "", data: null, fontes: [] },
  pontos_para_confirmacao: { ponto: "", motivo: null, fontes: [] } };
function collectFicha() {
  const f = JSON.parse(JSON.stringify(ATT.ficha_revisada));
  document.querySelectorAll("[data-fk]").forEach(el => { const k = el.dataset.fk;
    if (el.dataset.i === undefined) f[k] = el.value;
    else if (el.dataset.p) { const v = el.value; f[k][+el.dataset.i][el.dataset.p] = v === "" && f[k][+el.dataset.i][el.dataset.p] === null ? null : v; }
    else f[k][+el.dataset.i] = el.value; });
  return f;
}

/* ---------------- ações ---------------- */
async function save(silent) {
  if (ATT.status === "finalized") return;
  const body = { version: ATT.version, notes: $("#notes").value };
  if ($("#trRev")) body.transcript_revised = $("#trRev").value;
  if (ATT.ficha_revisada) body.ficha_revisada = collectFicha();
  ATT = await api(`/api/attendances/${ATT.id}`, { method: "PATCH", json: body });
  if (!silent) toast("Rascunho salvo");
}
async function act(name) {
  try {
    if (name === "copytr") { await navigator.clipboard.writeText(trText()); return toast("Transcrição copiada"); }
    if (name === "dltr") return baixarTranscricao();
    if (name === "save") { await save(); return render(true); }
    if (name === "retry") ATT = await api(`/api/attendances/${ATT.id}/retry`, { method: "POST" });
    if (name === "transcribe") { await save(true); ATT = await api(`/api/attendances/${ATT.id}/transcribe`, { method: "POST" }); }
    if (name === "analyze") { await save(true); ATT = await api(`/api/attendances/${ATT.id}/analyze-documents`, { method: "POST" }); }
    if (name === "generate") { await save(true); ATT = await api(`/api/attendances/${ATT.id}/generate`, { method: "POST" }); }
    if (name === "finalize") return finalizeDialog();
    render(true);
  } catch (e) { toast(e.message); }
}
function trText() { return $("#trRev") ? $("#trRev").value : (ATT.transcript.revised ?? ATT.transcript.original ?? ""); }
function baixarTranscricao() {
  const url = URL.createObjectURL(new Blob([trText()], { type: "text/plain;charset=utf-8" }));
  const l = document.createElement("a");
  l.href = url; l.download = `transcricao-atendimento-${ATT.id}.txt`; l.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function finalizeDialog() {
  const hasAudio = ATT.audio.status === "stored";
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" style="display:grid;gap:10px"><h2 style="margin:0">Finalizar atendimento</h2>
   <p>A ficha revisada será gravada como final e o atendimento ficará bloqueado para edição.</p>
   ${hasAudio ? `<div class="al bad">A gravação será <b>excluída definitivamente</b> deste sistema. Depois disso não será possível ouvir de novo nem retranscrever o áudio original. A exclusão vale para os arquivos controlados por este sistema; o tratamento de dados pela OpenAI segue as políticas do provedor.</div>
   <label class="row"><input type="checkbox" id="cfDel"> <span>Entendo e confirmo a exclusão do áudio.</span></label>` : ""}
   <div class="row"><span class="grow"></span><button class="btn" value="cancel">Cancelar</button><button class="btn pri" id="cfOk" value="ok">Finalizar</button></div></form>`;
  document.body.appendChild(d); d.showModal();
  d.addEventListener("close", async () => { const ok = d.returnValue === "ok"; const conf = hasAudio ? $("#cfDel")?.checked : false; d.remove();
    if (!ok) return; if (hasAudio && !conf) return toast("Confirme a exclusão do áudio para finalizar");
    try { await save(true); ATT = await api(`/api/attendances/${ATT.id}/finalize`, { method: "POST", json: { version: ATT.version, ficha_final: ATT.ficha_revisada, confirm_audio_deletion: !!conf } });
      REC.releaseAll(); toast(ATT.audio.status === "audio_deletion_pending" ? "Finalizado. A exclusão do áudio falhou e será repetida automaticamente." : "Atendimento finalizado"); render(); } catch (e) { toast(e.message); } });
}
async function uploadDocs(files) {
  files = [...files]; if (!files.length) return;
  const okExt = /\.(pdf|jpe?g|png)$/i, max = LIM.max_attachment_mb * 1048576;
  const bad = files.find(f => !okExt.test(f.name) || f.size > max);
  if (bad) return toast(`${bad.name}: ${!okExt.test(bad.name) ? "formato não aceito (use PDF, JPG ou PNG)" : "acima de " + LIM.max_attachment_mb + " MB"}`);
  if (ATT.documents.length + files.length > LIM.max_attachments) return toast(`Limite de ${LIM.max_attachments} anexos por atendimento`);
  const fd = new FormData(); files.forEach(f => fd.append("files", f, f.name));
  try { toast("Enviando documentos…"); ATT = await api(`/api/attendances/${ATT.id}/documents`, { method: "POST", body: fd }); render(true); toast("Documentos anexados"); } catch (e) { toast(e.message); }
}
function bind() {
  document.querySelectorAll("[data-a]").forEach(b => b.onclick = () => act(b.dataset.a));
  const c = $("#consent"); if (c) c.onchange = async () => { try { ATT = await api(`/api/attendances/${ATT.id}`, { method: "PATCH", json: { version: ATT.version, consent: c.checked } }); render(true); } catch (e) { toast(e.message); c.checked = !c.checked; } };
  const drop = $("#drop");
  if (drop) { ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => uploadDocs(e.dataTransfer.files)); $("#bAttach").onclick = e => { e.preventDefault(); $("#fAttach").click(); }; $("#fAttach").onchange = e => uploadDocs(e.target.files); }
  document.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "Confirmar"; return; }
    try { ATT = await api(`/api/attendances/${ATT.id}/documents/${b.dataset.rm}`, { method: "DELETE" }); render(true); } catch (e) { toast(e.message); } });
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = () => { const f = collectFicha(); f[b.dataset.del].splice(+b.dataset.i, 1); ATT.ficha_revisada = f; render(true); });
  document.querySelectorAll("[data-add]").forEach(b => b.onclick = () => { const f = collectFicha(); const k = b.dataset.add; f[k].push(k === "informacoes_ausentes" ? "" : JSON.parse(JSON.stringify(EMPTY_ITEM[k] || { descricao: "", fontes: [] }))); ATT.ficha_revisada = f; render(true); });
  document.querySelectorAll("[data-pull]").forEach(b => b.onclick = () => { const f = collectFicha(); f[b.dataset.pull] = JSON.parse(JSON.stringify(ATT.ai_latest.ficha[b.dataset.pull])); ATT.ficha_revisada = f; render(true); toast("Seção trazida da IA – salve o rascunho para gravar"); });
  if ($("#bStart")) REC.bindUI();
}

/* ---------------- gravação (getUserMedia + MediaRecorder) ---------------- */
const SEGMENT_SECONDS = 600; // partes de 10 min: cada uma é um arquivo independente, abaixo do limite de 25 MB da API
const REC = {
  state: "idle", stream: null, rec: null, chunks: [], seq: 0, elapsed: 0, segStart: 0, tick: null, last: 0, queue: [], ac: null, raf: null,
  mime() { return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || ""; },
  msg(h, cls = "") { const m = $("#recMsg"); if (m) m.innerHTML = h ? `<div class="al ${cls}">${h}</div>` : ""; },
  async listMics() { try { const ds = await navigator.mediaDevices.enumerateDevices(); const sel = $("#mic"); if (!sel) return; const cur = sel.value;
      sel.innerHTML = `<option value="">Padrão do sistema</option>` + ds.filter(d => d.kind === "audioinput").map((d, i) => `<option value="${esc(d.deviceId)}">${esc(d.label || "Microfone " + (i + 1))}</option>`).join(""); sel.value = cur; } catch (_) {} },
  bindUI() {
    $("#bStart").onclick = () => this.start(); $("#bPause").onclick = () => this.pause(); $("#bResume").onclick = () => this.resume(); $("#bStop").onclick = () => this.stop();
    if (this.state === "idle" && !this.queue.length) { this.seq = ATT.audio.segments.reduce((m, s) => Math.max(m, s.seq + 1), 0); this.elapsed = ATT.recording_seconds || 0; }
    this.listMics(); this.ui();
  },
  ui() { const s = this.state; const set = (id, d) => { const b = $(id); if (b) b.disabled = d; };
    set("#bStart", s !== "idle" || !ATT.consent.given); set("#bPause", s !== "recording"); set("#bResume", s !== "paused"); set("#bStop", s === "idle"); if ($("#mic")) $("#mic").disabled = s !== "idle";
    const dot = $("#dot"); if (dot) dot.classList.toggle("on", s === "recording");
    const t = Math.floor(this.elapsed), el = $("#timer"); if (el) el.textContent = `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
    if (!ATT.consent.given && s === "idle") this.msg("Registre a ciência e autorização do cliente para habilitar a gravação.");
  },
  async start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) return this.msg("Este navegador não permite gravar áudio. Use Chrome, Edge ou Firefox atualizados, em conexão segura (https).", "bad");
    if (this.elapsed >= LIM.max_recording_minutes * 60) return this.msg("Limite de duração da gravação atingido.", "bad");
    const dev = $("#mic").value;
    try { this.stream = await navigator.mediaDevices.getUserMedia({ audio: dev ? { deviceId: { exact: dev }, echoCancellation: true, noiseSuppression: true } : { echoCancellation: true, noiseSuppression: true } }); }
    catch (e) {
      const n = e && e.name;
      return this.msg(n === "NotAllowedError" || n === "SecurityError" ? "Permissão do microfone negada. Libere o microfone para este site nas configurações do navegador (ícone de cadeado na barra de endereço) e tente de novo."
        : n === "NotFoundError" || n === "OverconstrainedError" ? "Nenhum microfone encontrado. Conecte um microfone ou escolha outro na lista." : n === "NotReadableError" ? "O microfone está em uso por outro programa." : "Não foi possível acessar o microfone.", "bad");
    }
    try { ATT = await api(`/api/attendances/${ATT.id}`, { method: "PATCH", json: { version: ATT.version, status: "recording" } }); } catch (e) { this.release(); return this.msg(esc(e.message), "bad"); }
    this.listMics(); this.meter(); this.msg("");
    this.state = "recording"; this.newRecorder(); this.last = performance.now();
    this.tick = setInterval(() => this.onTick(), 500); this.ui();
    window.addEventListener("beforeunload", this.unload);
  },
  unload(e) { if (REC.state !== "idle" || REC.queue.length) { e.preventDefault(); e.returnValue = ""; } },
  newRecorder() {
    const mime = this.mime();
    this.rec = new MediaRecorder(this.stream, Object.assign({ audioBitsPerSecond: 32000 }, mime ? { mimeType: mime } : {}));
    this.chunks = []; this.segStart = this.elapsed;
    this.rec.ondataavailable = e => { if (e.data && e.data.size) this.chunks.push(e.data); };
    this.rec.onstop = () => { const blob = new Blob(this.chunks, { type: this.rec.mimeType || mime || "audio/webm" }); this.chunks = [];
      if (blob.size) this.enqueue(blob, this.elapsed - this.segStart); if (this.state === "rotating") { this.state = "recording"; this.newRecorder(); } };
    this.rec.start(1000);
  },
  onTick() { const t = performance.now(); if (this.state === "recording") this.elapsed += (t - this.last) / 1000; this.last = t; this.ui();
    if (this.state === "recording" && this.elapsed - this.segStart >= SEGMENT_SECONDS) { this.state = "rotating"; this.rec.stop(); }
    if (this.state === "recording" && this.elapsed >= LIM.max_recording_minutes * 60) { this.msg("Limite de duração atingido – gravação encerrada.", "bad"); this.stop(); } },
  pause() { if (this.rec && this.state === "recording") { this.rec.pause(); this.state = "paused"; this.ui(); } },
  resume() { if (this.rec && this.state === "paused") { this.rec.resume(); this.last = performance.now(); this.state = "recording"; this.ui(); } },
  async stop() { if (this.state === "idle") return; const r = this.rec; this.state = "stopping"; clearInterval(this.tick);
    await new Promise(res => { r.addEventListener("stop", res, { once: true }); r.stop(); });
    this.release(); this.state = "idle"; this.ui();
    await this.flush();
    try { ATT = await api(`/api/attendances/${ATT.id}`); ATT = await api(`/api/attendances/${ATT.id}`, { method: "PATCH", json: { version: ATT.version, status: "draft" } }); } catch (_) {}
    window.removeEventListener("beforeunload", this.unload); render(true);
  },
  release() { if (this.stream) this.stream.getTracks().forEach(t => t.stop()); this.stream = null; if (this.ac) { this.ac.close().catch(() => {}); this.ac = null; } cancelAnimationFrame(this.raf); },
  releaseAll() { this.release(); this.queue = []; this.chunks = []; this.rec = null; }, // descarta referências locais ao áudio
  enqueue(blob, dur) { this.queue.push({ blob, seq: this.seq++, dur }); this.flush(); },
  async flush() {
    if (this.flushing) return this.flushing; this.flushing = (async () => {
      while (this.queue.length) { const it = this.queue[0]; const ext = it.blob.type.includes("mp4") ? "m4a" : "webm";
        const fd = new FormData(); fd.append("seq", it.seq); fd.append("duration_s", Math.round(it.dur)); fd.append("file", it.blob, `parte_${it.seq}.${ext}`);
        try { const r = await fetch(`/api/attendances/${ATT.id}/audio`, { method: "POST", body: fd, credentials: "same-origin", headers: { "X-CSRF-Token": CSRF } });
          if (!r.ok) { const b = await r.json().catch(() => ({})); if (r.status >= 400 && r.status < 500 && r.status !== 409 && r.status !== 429) { this.msg("Parte da gravação recusada: " + esc(b.detail || r.status), "bad"); this.queue.shift(); continue; } throw new Error(b.detail || r.status); }
          this.queue.shift(); it.blob = null; // libera a referência local após envio confirmado
          this.msg(""); }
        catch (e) { this.msg(`Falha ao enviar parte da gravação (${esc(e.message)}). Nova tentativa em 5 s – não feche a página.`, "bad"); await new Promise(r => setTimeout(r, 5000)); }
      } })(); try { await this.flushing; } finally { this.flushing = null; }
  },
  meter() { try { this.ac = new AudioContext(); const src = this.ac.createMediaStreamSource(this.stream), an = this.ac.createAnalyser(); an.fftSize = 512; src.connect(an);
      const buf = new Uint8Array(an.fftSize);
      const draw = () => { const cv = $("#level"), g = cv && cv.getContext("2d"); if (!this.stream) return; if (!g) { this.raf = requestAnimationFrame(draw); return; } an.getByteTimeDomainData(buf); let m = 0; for (const v of buf) m = Math.max(m, Math.abs(v - 128)); g.clearRect(0, 0, cv.width, cv.height); g.fillStyle = "#8A2A47"; g.fillRect(0, 0, cv.width * Math.min(1, m / 64), cv.height); this.raf = requestAnimationFrame(draw); }; draw(); } catch (_) {} }
};
window.REC = REC;
boot();
