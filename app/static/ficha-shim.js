/* Adaptador da ficha de atendimento para o servidor próprio do escritório.
   A ficha foi escrita para o claude.ai e pede seus recursos por window.claude.use(nome).
   Aqui cada recurso é atendido pelas rotas /api/ficha/... deste servidor, com o login do escritório. */
(function () {
  "use strict";
  let ME = null, CSRF = "";
  const meP = fetch("/api/ficha/me", { credentials: "same-origin" }).then(async r => {
    if (r.status === 401) { location.href = "/?next=" + encodeURIComponent(location.pathname); throw new Error("login"); }
    if (!r.ok) throw new Error("me");
    ME = await r.json(); CSRF = ME.csrf; return ME;
  });

  const err = (code, message) => Object.assign(new Error(message || code), { code });
  async function api(path, opt = {}) {
    await meP;
    const o = Object.assign({ credentials: "same-origin", headers: {} }, opt);
    if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
    if (o.method && o.method !== "GET") o.headers["X-CSRF-Token"] = CSRF;
    let r;
    try { r = await fetch(path, o); } catch (_) { throw err("unavailable", "Servidor fora do ar"); }
    if (r.status === 401) { location.href = "/?next=" + encodeURIComponent(location.pathname); throw err("unauthenticated"); }
    if (r.status === 304) return r;
    if (r.status === 403) throw err("invalid_argument", "Sem permissão");
    if (r.status === 413) throw err("too_large", "Arquivo grande demais");
    if (r.status === 429) throw err("rate_limited", "Limite atingido");
    if (!r.ok) throw err(r.status >= 500 ? "unavailable" : "invalid_argument", "Erro " + r.status);
    return r;
  }

  /* ---------- db ---------- */
  const enc = encodeURIComponent;
  const snapDoc = (id, data) => ({ id, exists: data != null, data: () => (data == null ? undefined : JSON.parse(JSON.stringify(data))) });
  const subs = {}; // coleção -> {fns:[], etag, timer}
  async function pull(col, force) {
    const s = subs[col]; if (!s) return;
    const r = await api(`/api/ficha/db/${enc(col)}`, { headers: !force && s.etag ? { "If-None-Match": s.etag } : {} });
    if (r.status === 304) return;
    s.etag = r.headers.get("ETag");
    const body = await r.json();
    const snap = { docs: body.docs.map(d => snapDoc(d.id, d.data)), metadata: { fromCache: false, hasPendingWrites: false } };
    s.fns.forEach(([next]) => { try { next(snap); } catch (e) { console.error(e); } });
  }
  function poke(col) { if (subs[col]) setTimeout(() => pull(col).catch(() => {}), 0); }
  function subscribe(col, next, error) {
    let s = subs[col];
    if (!s) {
      s = subs[col] = { fns: [], etag: null };
      const tick = () => pull(col).catch(e => { if (e.code !== "unavailable") s.fns.forEach(([, er]) => er && er(e)); });
      s.timer = setInterval(() => { if (!document.hidden) tick(); }, 5000);
      document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
    }
    const entry = [next, error]; s.fns.push(entry);
    pull(col, true).catch(e => error && error(e));
    return () => { s.fns = s.fns.filter(x => x !== entry); };
  }
  const db = {
    collection(col) {
      return {
        doc(id) {
          const url = `/api/ficha/db/${enc(col)}/${enc(id)}`;
          return {
            id, path: col + "/" + id,
            async get() { const b = await (await api(url)).json(); return snapDoc(id, b.exists ? b.data : null); },
            async set(data) { await api(url, { method: "PUT", json: data }); poke(col); },
            async update(data) {
              const cur = await this.get(); if (!cur.exists) throw err("invalid_argument", "Documento não existe");
              await this.set(Object.assign(cur.data(), data));
            },
            async delete() { await api(url, { method: "DELETE" }); poke(col); },
          };
        },
        async get() { const b = await (await api(`/api/ficha/db/${enc(col)}`)).json(); return { docs: b.docs.map(d => snapDoc(d.id, d.data)) }; },
        onSnapshot(next, error) { return subscribe(col, next, error); },
      };
    },
  };

  /* ---------- usuário ---------- */
  const user = {
    async id() { return (await meP).id; },
    async isOwner() { return !!(await meP).isOwner; },
    async canEdit() { return true; },
    async me() { const m = await meP; return { id: m.id, name: m.name, email: null }; },
    async profiles(ids) { return (await api("/api/ficha/profiles", { method: "POST", json: { ids } })).json(); },
  };

  /* ---------- anexos ---------- */
  const assets = {
    async upload(blob) {
      const fd = new FormData(); fd.append("file", blob, blob.name || "arquivo");
      return (await api("/api/ficha/assets", { method: "POST", body: fd })).json();
    },
    async delete(id) { await api(`/api/ficha/assets/${enc(id)}`, { method: "DELETE" }); },
    async list() { return { assets: [], usage: {} }; },
  };

  /* ---------- downloads ---------- */
  const downloads = {
    async save({ filename, data }) {
      const blob = data instanceof Blob ? data : new Blob([data]);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = filename || "arquivo"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      return { saved: true };
    },
  };

  /* ---------- IA (OpenAI pelo servidor) ---------- */
  async function sampleCall(input, opts = {}, json = false) {
    const fd = new FormData();
    fd.append("input", typeof input === "string" ? input : JSON.stringify(input));
    fd.append("json", json ? "1" : "0");
    (opts.images || []).forEach((b, i) => fd.append("images", b, b.name || `imagem${i + 1}`));
    const r = await api("/api/ficha/ai", { method: "POST", body: fd, signal: opts.signal }).catch(e => { if (e.code === "invalid_argument") e.code = "not_granted"; throw e; });
    const b = await r.json();
    if (opts.onText) try { opts.onText({ text: b.text, delta: b.text }); } catch (_) {}
    return b;
  }
  const sample = Object.assign((input, opts) => sampleCall(input, opts, false).then(b => ({ text: b.text, truncated: !!b.truncated })), {
    json: (input, opts) => sampleCall(input, opts, true).then(b => b.value),
    limits: async () => { try { return (await api("/api/ficha/ai/limits")).json(); } catch (_) { return { images: null }; } },
  });

  /* ---------- conectores (Tramitação pelo servidor) ---------- */
  const mcp = {
    async callTool(server, tool, input) {
      if (server !== "Tramitação Inteligente") throw err("server_not_connected", "Indisponível no servidor do escritório");
      const r = await api(`/api/ficha/tramitacao/${enc(tool)}`, { method: "POST", json: input || {} }).catch(e => {
        if (e.code === "invalid_argument") e.code = "server_not_connected"; throw e; });
      return { payload: await r.json() };
    },
  };

  const CAPS = { db, user, assets, downloads, sample, mcp };
  window.claude = Object.freeze({ use: async name => { try { await meP; } catch (_) { return null; } return CAPS[name] || null; } });
})();
