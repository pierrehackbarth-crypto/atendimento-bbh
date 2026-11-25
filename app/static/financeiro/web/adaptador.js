/*
 * Adaptador da página RPV BANCOS para o THANOS (módulo verde – Financeiro).
 *
 * A página foi escrita para os serviços do claude.ai (window.claude.use("db" | "assets" | "downloads")).
 * Aqui as mesmas funções gravam no servidor do THANOS, com o login e as permissões de cada pessoa:
 *   db.collection("meses").get()      -> GET   /financeiro/api/meses
 *   db.doc("meses/2026-11").set(obj)  -> PUT   /financeiro/api/meses/2026-11   (importar o mês)
 *   db.doc("meses/2026-11").update(o) -> PATCH /financeiro/api/meses/2026-11   (conferidos e contabilidade)
 *   assets.upload(blob)               -> POST  /financeiro/api/arquivos        (guarda um PDF)
 *   assets.delete(id)                 -> DELETE /financeiro/api/arquivos/<id>
 *   downloads.save({filename, data})  -> baixa o arquivo no navegador
 */
(function () {
  const API = "/financeiro/api";
  let csrf = "";
  window.THANOS_FIN = {usuario: null};

  async function chamar(metodo, caminho, corpo, tipo) {
    const headers = {};
    if (metodo !== "GET") headers["X-CSRF-Token"] = csrf;
    if (corpo !== undefined) headers["Content-Type"] = tipo || "application/json";
    const r = await fetch(API + caminho, {method: metodo, credentials: "same-origin", cache: "no-store", headers,
      body: corpo === undefined ? undefined : (tipo ? corpo : JSON.stringify(corpo))});
    if (r.status === 401) { location.href = "/?next=/financeiro/"; throw {code: "login"}; }
    if (!r.ok) {
      let d = ""; try { d = (await r.json()).detail || ""; } catch (e) {}
      throw {code: r.status === 413 ? "too_large" : r.status === 403 ? "sem_permissao" : "erro", message: d || `erro ${r.status}`};
    }
    return r.json();
  }

  const pronto = (async () => {
    const r = await fetch(API + "/sessao", {credentials: "same-origin", cache: "no-store"});
    const s = await r.json();
    if (!s.usuario) { location.href = s.semAcesso ? "/financeiro/" : "/?next=/financeiro/"; throw {code: "login"}; }
    csrf = s.csrf || "";
    window.THANOS_FIN.usuario = s.usuario;
    document.dispatchEvent(new CustomEvent("thanos-fin-usuario", {detail: s.usuario}));
  })();

  const db = {
    collection(caminho) {
      return {
        async get() {
          await pronto;
          const {meses} = await chamar("GET", "/" + caminho);
          const docs = Object.entries(meses).map(([id, v]) => ({id, data: () => v}));
          return {docs, size: docs.length, empty: !docs.length};
        },
      };
    },
    doc(caminho) {
      return {
        set: async dados => { await pronto; return chamar("PUT", "/" + caminho, dados); },
        update: async campos => { await pronto; return chamar("PATCH", "/" + caminho, campos); },
      };
    },
  };

  const assets = {
    async upload(blob) { await pronto; return chamar("POST", "/arquivos", blob, "application/pdf"); },
    async delete(id) { await pronto; return chamar("DELETE", "/arquivos/" + encodeURIComponent(id)); },
  };

  const downloads = {
    async save({filename, data}) {
      const blob = data instanceof Blob ? data : new Blob([data]);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 60000);
      return {status: "saved"};
    },
  };

  const servicos = {db, assets, downloads};
  window.claude = {use: async nome => { await pronto; return servicos[nome] || null; }};
})();
