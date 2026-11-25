
const $ = s => document.querySelector(s);
const brl = v => (v == null || isNaN(v)) ? "" : v.toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const MESES = ["JANEIRO","FEVEREIRO","MARÇO","ABRIL","MAIO","JUNHO","JULHO","AGOSTO","SETEMBRO","OUTUBRO","NOVEMBRO","DEZEMBRO"];
// no THANOS cada pessoa tem permissões próprias (no claude.ai, sem THANOS_FIN, tudo liberado)
const pode = p => !window.THANOS_FIN || !window.THANOS_FIN.usuario || !!window.THANOS_FIN.usuario.perms[p];
document.addEventListener("thanos-fin-usuario", e => { const q = document.querySelector("#quem"); if (q) q.textContent = e.detail.nome; });
const idMes = mes => { const [m, a] = mes.split("."); return `${a}-${m.padStart(2, "0")}`; };

/* ---------- estado do mês aberto ---------- */
let db = null, assets = null;
let meses = {};            // id "2026-11" -> documento do mês
let atual = null;          // documento do mês aberto
let LEV = [], CONT = {BB: [], CEF: []}, PEND = [], CEF = [], cartas = [];
let conferido = new Set();
const chaveLev = l => `${l.banco}:${l.conta}:${l.rpv}`;

function usarMes(doc) {
  atual = doc;
  LEV = doc ? doc.lev || [] : [];
  CONT = doc ? doc.cont || {BB: [], CEF: []} : {BB: [], CEF: []};
  CONT.BB = CONT.BB || []; CONT.CEF = CONT.CEF || [];
  PEND = doc ? doc.pend || [] : [];
  CEF = LEV.filter(l => l.banco === "CEF");
  cartas = []; for (let i = 0; i < CEF.length; i += 5) cartas.push(CEF.slice(i, i + 5));
  conferido = new Set(doc ? doc.conferidos || [] : []);
  selDoc = cartas.length ? {t: "CEF", c: 0} : (LEV.find(l => l.banco === "BB") ? {t: "BB", l: LEV.find(l => l.banco === "BB")} : null);
  tiles(); tabelaLev(); renderDocs(); renderCont(); renderPend(); renderMeses();
}

/* ---------- banco de dados ---------- */
let salvarT = null, pendenteSalvar = {};
function salvar(campos) {
  if (!db || !atual) return;
  Object.assign(pendenteSalvar, campos);
  clearTimeout(salvarT);
  const id = idMes(atual.mes);
  salvarT = setTimeout(async () => {
    const p = pendenteSalvar; pendenteSalvar = {};
    try { await db.doc("meses/" + id).update(p); $("#mesNota").textContent = "alterações salvas"; }
    catch (e) { $("#mesNota").textContent = e && e.code === "sem_permissao" ? "sem permissão para alterar" : "não foi possível salvar as alterações"; }
  }, 800);
}
function opcoesMes() {
  const ids = Object.keys(meses).sort().reverse();
  $("#mesSel").innerHTML = ids.length ? ids.map(id => `<option value="${id}">${esc(meses[id].rotulo)}</option>`).join("")
    : '<option value="">Nenhum mês importado</option>';
  if (atual) $("#mesSel").value = idMes(atual.mes);
}
function renderMeses() {
  const ids = Object.keys(meses).sort().reverse();
  $("#listaMeses").innerHTML = ids.length ? ids.map(id => {
    const m = meses[id], q = (m.lev || []).length;
    const quando = m.importadoEm ? new Date(m.importadoEm).toLocaleString("pt-BR", {dateStyle: "short", timeStyle: "short"}) : "";
    return `<li aria-current="${atual && idMes(atual.mes) === id}"><b>${esc(m.rotulo)}</b><span>${q} contas · importado em ${esc(quando)}</span></li>`;
  }).join("") : '<li>Nenhum mês salvo ainda.</li>';
  opcoesMes();
}
$("#mesSel").addEventListener("change", e => { if (meses[e.target.value]) usarMes(meses[e.target.value]); });

async function iniciar() {
  const ok = await Promise.race([
    (async () => {
      db = window.claude ? await window.claude.use("db") : null;
      assets = window.claude ? await window.claude.use("assets") : null;
      return true;
    })(),
    new Promise(r => setTimeout(() => r(false), 10000)),
  ]);
  if (!ok || !db) {
    $("#mesNota").textContent = "banco de dados indisponível nesta visualização";
    $("#proc").title = "Importar precisa do banco de dados";
    usarMes(null); return;
  }
  try {
    const snap = await db.collection("meses").get();
    snap.docs.forEach(d => { meses[d.id] = d.data(); });
  } catch (e) { $("#mesNota").textContent = "não foi possível ler o banco de dados"; }
  const ids = Object.keys(meses).sort();
  usarMes(ids.length ? meses[ids[ids.length - 1]] : null);
}

/* ---------- abas ---------- */
const tabs = [...document.querySelectorAll("nav.steps button")];
function abrir(id) {
  tabs.forEach(b => b.setAttribute("aria-selected", b.dataset.tab === id));
  document.querySelectorAll("section").forEach(s => s.hidden = s.id !== id);
}
tabs.forEach(b => b.addEventListener("click", () => abrir(b.dataset.tab)));

/* ---------- entrada: selecionar pasta e importar ---------- */
let pacote = null, mesPasta = null;
$("#selPasta").addEventListener("change", e => {
  const arqs = [...e.target.files];
  if (!arqs.length) return;
  const caminho = f => f.webkitRelativePath || f.name;
  const pasta = caminho(arqs[0]).split("/")[0];
  const ehPdf = f => /[.]pdf$/i.test(f.name);
  const rel = arqs.filter(f => /^RelatorioProcessos.*[.]xlsx?$/i.test(f.name));
  const dem = arqs.filter(f => ehPdf(f) && /DEMTRANSF/i.test(f.name));
  const comp = arqs.filter(f => ehPdf(f) && /comp/i.test(caminho(f)) && /resg/i.test(caminho(f)));
  const clientes = new Set(dem.map(f => caminho(f).split("/").slice(1, -1).join("/")));
  $("#pastaOrigem").textContent = pasta;
  $("#p1").textContent = rel.length ? rel.map(f => f.name).join(", ") : "não está nesta pasta (o GERAR usa o da pasta Downloads)";
  $("#p2").textContent = `${dem.length} PDFs em ${clientes.size} pasta(s) de cliente`;
  $("#p3").textContent = comp.length ? `${comp.length} PDFs` : "nenhum encontrado";

  const m = pasta.match(/(\d{1,2})[.\-_ ](\d{4})/);
  mesPasta = m && +m[1] >= 1 && +m[1] <= 12 ? `${m[1].padStart(2, "0")}.${m[2]}` : null;
  pacote = mesPasta ? arqs.find(f => f.name.toLowerCase() === `rpv bancos - ${mesPasta}.zip`) || null : null;
  $("#proc").disabled = true;
  $("#bar").style.width = "0";
  if (!mesPasta) {
    $("#p4").textContent = "—";
    $("#procMsg").textContent = "O nome da pasta deve ser mês.ano, por exemplo 10.2026.";
    return;
  }
  const rotulo = `${MESES[+mesPasta.split(".")[0] - 1]} DE ${mesPasta.split(".")[1]}`;
  const ja = meses[idMes(mesPasta)];
  if (ja) usarMes(ja);
  if (!pacote) {
    $("#p4").textContent = "não encontrado";
    $("#procMsg").textContent = ja ? `${rotulo} já está salvo e foi aberto. Para atualizar, rode o GERAR RPV BANCOS deste mês e selecione a pasta de novo.`
      : `${rotulo} ainda não foi gerado. Rode o GERAR RPV BANCOS para ${mesPasta} e selecione a pasta de novo.`;
    return;
  }
  $("#p4").textContent = `${pacote.name} · ${(pacote.size / 1048576).toLocaleString("pt-BR", {maximumFractionDigits: 1})} MB`;
  $("#proc").textContent = ja ? `Atualizar ${rotulo}` : `Importar ${rotulo}`;
  $("#proc").disabled = !db || !assets || !pode("importar");
  $("#procMsg").textContent = !pode("importar") ? "Seu usuário pode consultar os meses, mas não importar. Peça ao administrador."
    : !db || !assets ? "Importar precisa do banco de dados e do armazenamento da página, que não estão disponíveis aqui."
    : ja ? "Este mês já está salvo: importar de novo substitui o que está salvo, inclusive conferências e ajustes." : "Pronto para importar.";
});

$("#proc").addEventListener("click", async () => {
  if (!pacote || !mesPasta || !db || !assets) return;
  const btn = $("#proc"), msg = $("#procMsg"), bar = $("#bar");
  btn.disabled = true;
  const passo = (t, f) => { msg.textContent = t; bar.style.width = (f * 100) + "%"; };
  try {
    passo("Abrindo o pacote do mês…", .05);
    const zip = await JSZip.loadAsync(pacote);
    const dados = JSON.parse(await zip.file("dados.json").async("string"));
    if (dados.mes !== mesPasta) throw new Error(`o pacote é de ${dados.mes}, não de ${mesPasta}`);
    const pdfs = Object.keys(zip.files).filter(n => /[.]pdf$/i.test(n)).sort();
    const arquivos = {cef: {}};
    for (let i = 0; i < pdfs.length; i++) {
      passo(`Guardando os PDFs (${i + 1} de ${pdfs.length})…`, .1 + .8 * i / pdfs.length);
      const blob = new Blob([await zip.file(pdfs[i]).async("arraybuffer")], {type: "application/pdf"});
      const up = await assets.upload(blob);
      const ref = {id: up.id, url: up.url};
      if (pdfs[i] === "bb.pdf") arquivos.bb = ref;
      else { const n = (pdfs[i].match(/carta(\d+)/) || [])[1]; if (n) arquivos.cef[n] = ref; }
    }
    passo("Salvando no banco de dados…", .93);
    const antigo = meses[idMes(mesPasta)];
    const doc = Object.assign(dados, {arquivos, conferidos: [], importadoEm: new Date().toISOString()});
    await db.doc("meses/" + idMes(mesPasta)).set(doc);
    if (antigo && antigo.arquivos) {  // apaga os PDFs da importação anterior deste mês
      const velhos = [antigo.arquivos.bb, ...Object.values(antigo.arquivos.cef || {})].filter(a => a && a.id);
      for (const a of velhos) { try { await assets.delete(a.id); } catch (e) {} }
    }
    meses[idMes(mesPasta)] = doc;
    passo("", 1);
    msg.innerHTML = `<span class="ok">Importado:</span> ${esc(doc.rotulo)} · ${doc.lev.length} contas, ${doc.pend.length} pendências.`;
    btn.textContent = `Atualizar ${doc.rotulo}`;
    usarMes(doc);
    setTimeout(() => abrir("lev"), 700);
  } catch (e) {
    const code = e && e.code;
    msg.textContent = code === "sem_permissao" ? "Seu usuário não tem permissão para importar meses."
      : code === "quota_or_state" || code === "quota_exceeded" ? "O armazenamento da página está cheio: apague um mês antigo antes de importar."
      : code === "too_large" ? "Um dos PDFs passa de 40 MB e não pôde ser guardado."
      : "Não foi possível importar: " + (e && e.message ? e.message : "erro desconhecido") + ".";
  } finally { btn.disabled = false; }
});

/* ---------- levantamentos ---------- */
let fB = "";
function soma(arr) { return arr.reduce((a, l) => a + (l.valor || 0), 0); }
function cartaDe(l) { return cartas.findIndex(c => c.includes(l)); }
function pedido(l) { return l.banco === "BB" ? "Formulário BB" : "Carta CEF " + String(cartaDe(l) + 1).padStart(2, "0"); }
function pendAbertas() {
  let n = PEND.length;
  ["BB", "CEF"].forEach(b => CONT[b].forEach(r => { if (r.conferir) n++; }));
  return n;
}
function tiles() {
  const bb = LEV.filter(l => l.banco === "BB");
  const conf = LEV.filter(l => conferido.has(chaveLev(l))).length;
  $("#tiles").innerHTML = `
    <div class="tile"><div class="k">Banco do Brasil</div><div class="v">R$ ${brl(soma(bb))}</div><div class="s">${bb.length} contas · ${bb.length} formulários</div></div>
    <div class="tile"><div class="k">Caixa</div><div class="v">R$ ${brl(soma(CEF))}</div><div class="s">${CEF.length} RPVs · ${cartas.length} cartas</div></div>
    <div class="tile"><div class="k">Total do mês</div><div class="v">R$ ${brl(soma(LEV))}</div><div class="s">${new Set(LEV.map(l => l.cliente)).size} clientes</div></div>
    <div class="tile"><div class="k">Conferidos</div><div class="v">${conf} / ${LEV.length}</div><div class="s">${pendAbertas()} pendências abertas</div></div>`;
}
function tabelaLev() {
  if (!LEV.length) { $("#tLev tbody").innerHTML = '<tr><td colspan="9" class="note">Nenhum mês aberto. Importe um mês na etapa 1.</td></tr>'; return; }
  const q = ($("#busca").value || "").toLowerCase();
  const rows = LEV.filter(l => (!fB || l.banco === fB) && (!q || (l.cliente + l.rpv + l.originario).toLowerCase().includes(q)));
  $("#tLev tbody").innerHTML = rows.map(l => {
    const i = LEV.indexOf(l);
    const suc = /sucumb/i.test(l.tipo);
    return `<tr class="click" data-i="${i}">
      <td><span class="chip ${esc(l.banco)}">${esc(l.banco)}</span></td><td>${esc(l.cliente)}</td><td>${esc(l.filial)}</td>
      <td>${suc ? '<span class="chip suc">Sucumbência</span>' : "Contratuais"}</td>
      <td class="mono">${esc(l.rpv)}</td><td class="mono">${esc(l.conta)}</td><td class="num">${brl(l.valor)}</td>
      <td>${pedido(l)}</td>
      <td><input type="checkbox" aria-label="Conferido" data-c="${i}" ${conferido.has(chaveLev(l)) ? "checked" : ""} ${pode("editar") ? "" : "disabled"}></td></tr>`;
  }).join("") + `<tr class="tot"><td colspan="6">Total (${rows.length})</td><td class="num">${brl(soma(rows))}</td><td colspan="2"></td></tr>`;
}
$("#tLev").addEventListener("click", e => {
  if (e.target.dataset.c !== undefined) {
    const k = chaveLev(LEV[+e.target.dataset.c]);
    e.target.checked ? conferido.add(k) : conferido.delete(k);
    tiles(); salvar({conferidos: [...conferido]}); return;
  }
  const tr = e.target.closest("tr[data-i]"); if (!tr) return;
  const l = LEV[+tr.dataset.i];
  selDoc = l.banco === "BB" ? {t: "BB", l} : {t: "CEF", c: cartaDe(l)};
  renderDocs(); abrir("docs");
});
$("#fBanco").addEventListener("click", e => {
  if (!e.target.dataset || e.target.dataset.b === undefined) return;
  fB = e.target.dataset.b;
  [...$("#fBanco").children].forEach(b => b.setAttribute("aria-pressed", b === e.target)); tabelaLev();
});
$("#busca").addEventListener("input", tabelaLev);

/* ---------- pedidos ---------- */
let selDoc = null;
function dataPed() { return (atual && atual.dataPedido) || {dia: "", mes: "", ano: ""}; }
function bbForm(l) {
  const x = '<span class="x">X</span>', o = '<span class="x"></span>', d = dataPed();
  return `<div class="bbform">
    <div class="head"><div class="logo">BB</div><div><b>Formulário de Solicitação de Resgate de Depósito Judicial / Precatório</b><br>EXCETO DO TRIBUNAL DE JUSTIÇA DO ESTADO DE SÃO PAULO</div></div>
    <b>Beneficiário indicado no Documento de Levantamento:</b>
    <div class="sec">Nome: <span class="f">BUSS E HACKBARTH ADVOGADOS</span> CPF/CNPJ: <span class="f">18.271.295/0001-04</span></div>
    <b>Representante Legal / Procurador:</b>
    <div class="sec">Nome: <span class="f">JORGE BUSS</span> CPF/CNPJ: <span class="f">036.996.859-00</span></div>
    <div class="sec">${x}Depósito Judicial ${o}Precatório com Alvará ${o}Precatório sem Alvará</div>
    <div class="sec">Conta(s) Judicial(ais): <span class="f hl">${esc(l.conta)}</span></div>
    <div class="sec">${x}<b>CRÉDITO Conta BB ou TED para o REPRESENTANTE LEGAL</b></div>
    <div class="sec">Banco: <span class="f">001</span> <span class="f">BANCO DO BRASIL</span> Agência: <span class="f">629-7</span> Conta: <span class="f">40804-2</span></div>
    <div class="sec">Nome: <span class="f">BUSS E HACKBARTH ADVOGADOS</span> CPF/CNPJ: <span class="f">18.271.295/0001-04</span></div>
    <div class="sec">Tipo: ${x}Conta Corrente · Valor: ${x}Total</div>
    <div class="sec"><b>IMPOSTO DE RENDA</b> · Declaração de isenção I.R.R.F: ${o}SIM ${x}NÃO</div>
    <div class="sec">Telefone: <span class="f">(47) 3035-3944</span></div>
    <div class="sec">Local e Data: <span class="f">TIMBÓ</span>, <span class="f hl">${esc(d.dia)}</span> de <span class="f hl">${esc(d.mes)}</span> de <span class="f hl">${esc(d.ano)}</span></div>
    <p style="margin-top:18px;text-align:center;border-top:1px solid #111;padding-top:4px">Assinatura do beneficiário ou representante legal</p>
    <p class="note" style="color:#555">Cliente: ${esc(l.cliente)} · RPV ${esc(l.rpv)} · R$ ${brl(l.valor)} (${esc(l.tipo)})</p>
  </div>`;
}
function cefCarta(c) {
  const rs = cartas[c], d = dataPed();
  return `<div class="cefhead"><b>CAIXA</b><span>Autorização para Crédito em Conta – Pessoa Jurídica</span></div>
    <p style="text-align:justify">A empresa BUSS E HACKBARTH ADVOGADOS, CNPJ 18.271.295/0001-04, estabelecida em (Timbó/SC), representada por JORGE BUSS, CASADO, CPF nº 036.996.859-00, por este documento, AUTORIZA a CAIXA – Agência 0809 a proceder com o pagamento do Precatório / Requisição de Pequeno Valor - RPV referente ao processo nº <span class="hl">${rs.map(r => esc(r.rpv)).join(" / ")}</span>, por meio do crédito na conta de titularidade da empresa conforme abaixo:</p>
    <table><thead><tr><th>Banco</th><th>Agência</th><th>Tipo de Conta</th><th>Nº Conta com DV</th><th>Valor FIXO</th><th>Percentual</th></tr></thead>
    <tbody>${rs.map(r => `<tr><td>104</td><td>0809</td><td>CC</td><td>579173312-3</td><td class="hl">R$ ${brl(r.valor)}</td><td></td></tr>`).join("")}</tbody></table>
    <p>Em anexo, envio cópia dos seguintes documentos: ☐ Documento de Identidade; ☐ CPF; ☐ CNPJ da empresa; ☐ Contrato Social, com a indicação de poderes do representante.</p>
    <p style="text-align:justify">O representante confirma a autenticidade dos documentos encaminhados e assume a total responsabilidade, civil e criminal, pelos documentos apresentados.</p>
    <p>TIMBÓ, ${esc(`${d.dia} DE ${String(d.mes).toUpperCase()} DE ${d.ano}`)}</p>
    <p style="margin-top:22px">Nome do Sacador JORGE BUSS (Representante Legal da Empresa BUSS E HACKBARTH ADVOGADOS / CNPJ 18.271.295/0001-04) · CPF: 036.996.859-00</p>
    <p class="note" style="color:#555;font-family:Arial,sans-serif;font-size:12px">Clientes nesta carta: ${rs.map(r => esc(r.cliente)).join(", ")} · Fonte Bookman Old Style 12</p>`;
}
function renderDocs() {
  const bb = LEV.filter(l => l.banco === "BB");
  let h = `<div class="grp">Caixa · ${cartas.length} cartas</div>`;
  cartas.forEach((c, i) => {
    const cur = selDoc && selDoc.t === "CEF" && selDoc.c === i;
    h += `<button data-c="${i}" aria-current="${cur}"><span>Carta ${String(i + 1).padStart(2, "0")} · ${c.length} RPVs</span><span class="mono">PDF</span></button>`;
  });
  h += `<div class="grp">Banco do Brasil · ${bb.length} formulários</div>`;
  if (bb.length) h += `<button id="baixarTodosBB"><span><b>Todos em 1 PDF</b><br><span class="note">cada formulário seguido do seu demonstrativo</span></span><span class="mono">PDF</span></button><div class="note" id="dlTodos" style="padding:0 12px"></div>`;
  bb.forEach(l => {
    const cur = selDoc && selDoc.t === "BB" && selDoc.l === l;
    h += `<button data-i="${LEV.indexOf(l)}" aria-current="${cur}"><span>${esc(l.cliente)}</span><span class="mono"></span></button>`;
  });
  $("#docList").innerHTML = h;
  if (!LEV.length || !selDoc) {
    $("#paper").innerHTML = '<p>Nenhum pedido neste mês. Importe um mês na etapa 1.</p>';
    $("#confirmBox").innerHTML = '';
    return;
  }
  $("#paper").innerHTML = selDoc.t === "BB" ? bbForm(selDoc.l) : cefCarta(selDoc.c);
  $("#confirmBox").innerHTML = `<div class="note" id="dlMsg"></div><div class="row"><button class="btn primary" id="baixarPdf">Baixar PDF</button></div>`;
}
$("#docList").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.id === "baixarTodosBB") {
    const a = atual.arquivos && atual.arquivos.bb;
    salvarArquivo(a && a.url, `BB - formularios e RPVs - ${atual.mes}.pdf`, $("#dlTodos")); return;
  }
  selDoc = b.dataset.c !== undefined ? {t: "CEF", c: +b.dataset.c} : {t: "BB", l: LEV[+b.dataset.i]};
  renderDocs();
});
async function baixarPdf(url) {
  if (!url) throw {code: "sem_arquivo"};
  const r = await fetch(url);
  if (!r.ok) throw {code: "fetch"};
  return r.blob();
}
async function salvarArquivo(urlOuBlob, nome, msg) {
  msg.textContent = "Preparando o PDF…";
  const dl = window.claude ? await window.claude.use("downloads") : null;
  if (!dl) { msg.textContent = "O download não está disponível nesta visualização."; return; }
  try {
    const blob = typeof urlOuBlob === "string" || !urlOuBlob ? await baixarPdf(urlOuBlob) : await urlOuBlob();
    await dl.save({filename: nome, data: blob});
    msg.textContent = "PDF salvo: " + nome;
  } catch (e) {
    msg.textContent = e && e.code === "declined" ? "Download cancelado." :
      e && e.code === "rate_limited" ? "Aguarde um instante e tente de novo." :
      e && e.code === "sem_arquivo" ? "Este mês não tem esse PDF no pacote." : "Não foi possível baixar este PDF.";
  }
}
async function formularioBB(l) {   // recorta o formulário do PDF único do BB
  const a = atual.arquivos && atual.arquivos.bb;
  if (!l.pag || !a) throw {code: "sem_arquivo"};
  const todo = await PDFLib.PDFDocument.load(await (await baixarPdf(a.url)).arrayBuffer());
  const so = await PDFLib.PDFDocument.create();
  const idx = Array.from({length: l.pag[1]}, (_, k) => l.pag[0] + k);
  (await so.copyPages(todo, idx)).forEach(p => so.addPage(p));
  return new Blob([await so.save()], {type: "application/pdf"});
}
$("#confirmBox").addEventListener("click", e => {
  if (e.target.id !== "baixarPdf" || !selDoc) return;
  if (selDoc.t === "BB") {
    const l = selDoc.l;
    salvarArquivo(() => formularioBB(l), `Formulario BB - ${l.cliente} - conta ${l.conta}.pdf`, $("#dlMsg"));
  } else {
    const n = String(selDoc.c + 1).padStart(2, "0");
    const a = atual.arquivos && atual.arquivos.cef && atual.arquivos.cef[n];
    salvarArquivo(a && a.url, `Autorizacao CEF - carta ${n} com RPVs - ${atual.mes}.pdf`, $("#dlMsg"));
  }
});

/* ---------- contabilidade ---------- */
let cB = "BB";
function liq(r) { return (+r.capital || 0) - (+r.ir || 0) - (+r.tarifa || 0); }
function num(v) { const n = parseFloat(String(v).replace(/\./g, "").replace(",", ".")); return isNaN(n) ? 0 : n; }
function renderCont() {
  const rows = CONT[cB], so = $("#soConf").checked;
  const amar = rows.filter(r => r.conferir).length;
  $("#contSub").textContent = `RPVs - ${cB === "BB" ? "Banco do Brasil" : "Caixa Econômica Federal"} · ${atual ? atual.rotulo : ""} · ${rows.length} lançamentos, ${amar} para conferir.`;
  const vis = rows.map((r, i) => [r, i]).filter(([r]) => !so || r.conferir);
  if (!rows.length) { $("#tCont tbody").innerHTML = '<tr><td colspan="8" class="note">Nenhum lançamento neste mês. Rode o GERAR CONTABILIDADE e importe o mês de novo.</td></tr>'; return; }
  const ro = pode("editar") ? "" : " readonly";
  $("#addLinha").disabled = !pode("editar");
  $("#tCont tbody").innerHTML = vis.map(([r, i]) => `<tr class="${r.conferir ? "warn" : ""}">
    <td>${r.novo ? `<input class="txt" data-i="${i}" data-k="nome" value="${esc(r.nome)}" aria-label="Cliente"${ro}>` : esc(r.nome)}${r.conferir ? `<span class="why">${esc(r.conferir)}</span>` : ""}</td>
    <td class="mono">${r.novo ? `<input class="txt" style="min-width:120px" data-i="${i}" data-k="cpf" value="${esc(r.cpf)}" aria-label="CPF"${ro}>` : esc(r.cpf) || "—"}</td>
    <td class="num"><input class="cell" data-i="${i}" data-k="capital" value="${brl(r.capital)}" aria-label="Capital"${ro}></td>
    <td class="num"><input class="cell" data-i="${i}" data-k="ir" value="${brl(r.ir)}" aria-label="IR"${ro}></td>
    <td class="num">${brl(r.tarifa)}</td>
    <td class="num">${brl(liq(r))}</td>
    <td class="mono">${esc(r.data)}</td>
    <td><input class="txt" data-i="${i}" data-k="obs" value="${esc(r.obs)}" aria-label="Observação"${ro}></td></tr>`).join("") + totCont(rows);
}
function totCont(rows) {
  const s = k => rows.reduce((a, r) => a + (+r[k] || 0), 0);
  return `<tr class="tot"><td colspan="2">TOTAIS</td><td class="num">${brl(s("capital"))}</td><td class="num">${brl(s("ir"))}</td><td class="num">${brl(s("tarifa"))}</td><td class="num">${brl(rows.reduce((a, r) => a + liq(r), 0))}</td><td colspan="2"></td></tr>`;
}
$("#tCont").addEventListener("change", e => {
  if (!pode("editar")) return;
  const i = e.target.dataset.i, k = e.target.dataset.k; if (i === undefined) return;
  const r = CONT[cB][+i];
  if (k === "capital" || k === "ir") {
    r[k] = num(e.target.value); e.target.value = brl(r[k]);
    if (r.credito && k === "capital") {
      r.obs = `Obs: Entrou na conta o valor de R$ ${brl(r.credito)} entretanto foi repassado ao cliente o valor de R$ ${brl(r.credito - r.capital)}`;
      r.conferir = "";
    }
  } else r[k] = e.target.value;
  renderCont(); tiles(); renderPend(); salvar({cont: CONT});
});
$("#cBanco").addEventListener("click", e => {
  if (!e.target.dataset || !e.target.dataset.b) return;
  cB = e.target.dataset.b;
  [...$("#cBanco").children].forEach(b => b.setAttribute("aria-pressed", b === e.target)); renderCont();
});
$("#soConf").addEventListener("change", renderCont);
$("#addLinha").addEventListener("click", () => {
  if (!atual || !pode("editar")) return;
  CONT[cB].push({nome: "", cpf: "", capital: 0, ir: 0, tarifa: 0, data: "", obs: "Ajuste manual", conferir: "linha de ajuste: preencher", novo: true});
  $("#soConf").checked = false; renderCont(); renderPend(); salvar({cont: CONT});
});

/* ---------- pendências ---------- */
function renderPend() {
  const extra = [];
  ["BB", "CEF"].forEach(b => CONT[b].forEach(r => { if (r.conferir) extra.push({item: `Contabilidade ${b}: ${r.nome || "linha nova"}`, motivo: r.conferir}); }));
  const todas = PEND.map(p => ({item: `${p.item} · ${p.cliente}`, motivo: p.motivo})).concat(extra);
  $("#pendCount").textContent = todas.length || "";
  if (!todas.length) { $("#pendList").innerHTML = `<li>Nenhuma pendência${atual ? " em " + esc(atual.rotulo.toLowerCase()) : ""}.</li>`; return; }
  $("#pendList").innerHTML = todas.map(p => `<li>${esc(p.motivo)}<span>${esc(p.item)}</span></li>`).join("");
}

usarMes(null);
iniciar();
