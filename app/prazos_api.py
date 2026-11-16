"""THANOS – módulo AMARELO (Controle de Prazos).

Traz para dentro do THANOS o sistema "Prazos Buss & Hackbarth" (antes um servidor Node.js separado, com login próprio).
Agora usa o mesmo login, a mesma sessão (com proteção CSRF) e as mesmas permissões por pessoa do THANOS.

Os prazos ficam em data/prazos/ (dentro da pasta que já entra na cópia de segurança diária):
  prazos.json ........ prazos e configurações (mesmo formato do sistema antigo, para importar direto)
  atividade.jsonl .... registro de quem fez o quê (base da aba Produtividade)
  backup/ ............ uma cópia por dia, feita ANTES da primeira alteração do dia (guarda 60 dias),
                       e uma cópia extra antes de cada exclusão em lote
"""
import json, os, re, shutil, threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from .config import get_settings
from .models import User
from .security import get_db, current_user, optional_user
from .permissions import has

router = APIRouter(prefix="/prazos/api")
FUSO = ZoneInfo("America/Sao_Paulo")

# permissão da tela antiga  ->  permissão do THANOS
MAPA_PERMS = {
    "importar": "prazos_importar", "exportar": "prazos_exportar", "definirEquipe": "prazos_equipe",
    "editarOutra": "prazos_editar_outra", "excluirPropria": "prazos_excluir_propria", "excluirOutra": "prazos_excluir_outra",
    "baixaManual": "prazos_baixa", "configurar": "prazos_configurar", "relatorio": "prazos_produtividade",
}

# ---------------------------------------------------------------- dados
DIA_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RX = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
TEXTOS = {  # campo -> tamanho máximo
    "proc": 40, "cliente": 300, "contra": 300, "cpf": 20, "papel": 80, "classe": 300, "assunto": 300,
    "evento": 600, "tipo": 80, "envio": 40, "inicio": 40, "final": 40, "imp": 40, "baixa": 40, "orgao": 80,
    "trib": 40, "prov": 600, "obs": 6000, "cat": 120,
}
CAMPOS_TELA = {"prov", "obs", "edOk", "st", "eq", "eqAuto", "baixa"}  # o que a tela pode mudar num prazo já existente


def _limpa_item(p: dict, so_tela: bool) -> dict:
    """Aceita só campos conhecidos, com o tipo e o tamanho certos. Campo estranho é descartado."""
    if not isinstance(p, dict):
        raise HTTPException(400, "Prazo inválido")
    out = {}
    for k, v in p.items():
        if so_tela and k not in CAMPOS_TELA:
            continue
        if k in TEXTOS:
            out[k] = "" if v is None else str(v)[:TEXTOS[k]]
        elif k == "st":
            out[k] = "cumprido" if v == "cumprido" else "pendente"
        elif k == "eq":
            out[k] = v if v in (1, 2) and not isinstance(v, bool) else None
        elif k in ("eqAuto", "edOk"):
            out[k] = bool(v)
        elif k == "dias":
            out[k] = v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 3650 else None
    if so_tela and out.get("baixa"):
        out["baixa"] = ""  # a "baixa automática" só vem da importação da planilha
    return out


def _limpa_config(c) -> dict:
    if not isinstance(c, dict):
        raise HTTPException(400, "Configuração inválida")
    if len(json.dumps(c)) > 1_000_000:
        raise HTTPException(413, "Configuração grande demais")
    tipos = {"regras": list, "regrasCampo": list, "links": dict, "comarcas": dict, "diasExtras": list, "nomes": dict}
    out = {}
    for k, t in tipos.items():
        v = c.get(k)
        if v is None:
            continue
        if not isinstance(v, t):
            raise HTTPException(400, f"Configuração inválida ({k})")
        out[k] = v
    for trib, url in (out.get("links") or {}).items():
        u = str(url or "").strip()
        if u and not re.match(r"^https?://", u, re.I):
            raise HTTPException(400, f"O link de {trib} precisa começar com https://")
    for k in ("comarcas", "nomes", "links"):
        if k in out:
            out[k] = {str(a)[:80]: str(b or "")[:500] for a, b in out[k].items()}
    return out


class Loja:
    """Guarda os prazos num arquivo JSON, com gravação atômica, trava e cópias de segurança."""

    def __init__(self, pasta: str):
        self.pasta = os.path.abspath(pasta)
        self.arq = os.path.join(self.pasta, "prazos.json")
        self.log = os.path.join(self.pasta, "atividade.jsonl")
        self.bkp = os.path.join(self.pasta, "backup")
        os.makedirs(self.bkp, exist_ok=True)
        self.trava = threading.RLock()
        self.estado = {"dias": {}, "config": None, "rev": 1}
        if os.path.exists(self.arq):
            with open(self.arq, encoding="utf-8") as f:
                self.estado.update(json.load(f))
        self.estado["rev"] = int(self.estado.get("rev") or 1)

    def _copia(self, nome):
        if os.path.exists(self.arq):
            shutil.copy2(self.arq, os.path.join(self.bkp, nome))

    def gravar(self):
        hoje = datetime.now(FUSO).date().isoformat()
        if not os.path.exists(os.path.join(self.bkp, f"prazos-{hoje}.json")):
            self._copia(f"prazos-{hoje}.json")  # cópia do dia ANTES de alterar (o antigo copiava depois)
        self.estado["rev"] += 1
        tmp = self.arq + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.estado, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.arq)
        diarias = sorted(x for x in os.listdir(self.bkp) if re.match(r"^prazos-\d{4}-\d{2}-\d{2}\.json$", x))
        for velho in diarias[:-60]:
            os.remove(os.path.join(self.bkp, velho))
        extras = sorted(x for x in os.listdir(self.bkp) if x.startswith("prazos-antes-apagar-"))
        for velho in extras[:-30]:
            os.remove(os.path.join(self.bkp, velho))

    def registrar(self, linhas):
        if linhas:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in linhas))


_loja: Loja | None = None
_loja_trava = threading.Lock()


def loja() -> Loja:
    global _loja
    pasta = os.path.abspath(get_settings().prazos_dir)
    with _loja_trava:
        if _loja is None or _loja.pasta != pasta:
            _loja = Loja(pasta)
        return _loja


# ---------------------------------------------------------------- permissões
def prazos_user(user: User = Depends(current_user)) -> User:
    if not has(user, "prazos"):
        raise HTTPException(403, "Seu usuário não tem acesso ao Controle de Prazos. Peça ao administrador.")
    return user


def _admin(u: User) -> bool:
    return u.role == "admin"


def pode(u: User, p: str) -> bool:
    return _admin(u) or has(u, MAPA_PERMS[p])


def publico(u: User) -> dict:
    return {"id": u.id, "nome": u.name, "login": u.email, "equipe": u.prazos_equipe if u.prazos_equipe in (1, 2) else None,
            "admin": _admin(u), "ativo": bool(u.active), "perms": {k: pode(u, k) for k in MAPA_PERMS}}


def checar(u: User, item, patch, origem) -> str | None:
    """Mesmas regras do sistema antigo. Devolve o motivo da recusa, ou None se pode."""
    if origem == "importacao":
        return None if pode(u, "importar") else "importar planilhas"
    if origem == "regras":
        return None if pode(u, "configurar") else "alterar configurações"
    if _admin(u):
        return None
    eq_u = u.prazos_equipe if u.prazos_equipe in (1, 2) else None
    outra = bool(item and item.get("eq") is not None and eq_u is not None and item.get("eq") != eq_u)
    if patch is None:
        if outra:
            return None if pode(u, "excluirOutra") else "excluir prazos da outra equipe"
        return None if pode(u, "excluirPropria") else "excluir prazos"
    if not item:
        return "criar prazos fora da importação"
    if "eq" in patch:
        sugestao = (patch.get("eqAuto") is True or patch.get("eq") is None) and (item.get("eq") is None or item.get("eqAuto"))
        if not sugestao and not pode(u, "definirEquipe"):
            return "definir a equipe do prazo"
    if "st" in patch and patch["st"] != (item.get("st") or "pendente") and not pode(u, "baixaManual"):
        return "marcar como cumprido ou reabrir prazos"
    if any(k in patch for k in ("prov", "obs", "edOk", "st")) and outra and not pode(u, "editarOutra"):
        return "editar prazos da outra equipe"
    return None


async def _corpo(request: Request):
    if int(request.headers.get("content-length") or 0) > 20 * 1024 * 1024:
        raise HTTPException(413, "Arquivo grande demais")
    try:
        return await request.json()
    except ValueError:
        raise HTTPException(400, "Dados inválidos")


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- rotas
@router.get("/sessao")
def sessao(request: Request, db=Depends(get_db)):
    u = optional_user(request, db)
    if not u:
        return {"usuario": None, "login": "/?next=/prazos/"}
    if not has(u, "prazos"):
        return {"usuario": None, "semAcesso": True, "nome": u.name}
    from .security import _th, COOKIE
    from .models import SessionToken
    st = db.get(SessionToken, _th(request.cookies.get(COOKIE, "")))
    return {"usuario": publico(u), "csrf": st.csrf if st else ""}


@router.get("/estado")
def estado(user=Depends(prazos_user), db=Depends(get_db)):
    L = loja()
    nomes = {x.id: x.name for x in db.scalars(select(User))}
    with L.trava:
        return {**L.estado, "nomes": nomes}


@router.get("/rev")
def rev(user=Depends(prazos_user)):
    return {"rev": loja().estado["rev"]}


@router.post("/dias/{d}")
async def gravar_dia(d: str, request: Request, user=Depends(prazos_user)):
    if not DIA_RX.match(d):
        raise HTTPException(404, "Data inválida")
    corpo = await _corpo(request)
    itens = corpo.get("items") if isinstance(corpo, dict) else None
    if not isinstance(itens, dict) or len(itens) > 5000:
        raise HTTPException(400, "items ausente")
    origem = corpo.get("origem") if corpo.get("origem") in ("importacao", "regras") else "manual"
    L = loja()
    with L.trava:
        dia = L.estado["dias"].get(d) or {"data": d, "items": {}}
        limpos = {}
        for iid, patch in itens.items():
            if not ID_RX.match(str(iid)):
                raise HTTPException(400, "Identificador de prazo inválido")
            antes = dia["items"].get(iid)
            if patch is not None:
                patch = _limpa_item(patch, so_tela=(origem == "manual" and antes is not None))
            negado = checar(user, antes, patch, origem)
            if negado:
                raise HTTPException(403, f"Você não tem permissão para {negado}.")
            if patch is not None and antes is None and not patch.get("proc"):
                raise HTTPException(400, "Prazo sem número de processo")
            limpos[iid] = patch
        L.estado["dias"][d] = dia
        agora = _agora()
        log, novos = [], 0
        for iid, p2 in limpos.items():
            antes = dia["items"].get(iid)
            base = {"t": agora, "u": user.id, "d": d, "id": iid, "p": (antes or {}).get("proc") or (p2 or {}).get("proc") or ""}
            if p2 is None:
                if antes:
                    log.append({"a": "exclusao", **base})
                dia["items"][iid] = None
                continue
            if not antes:
                novos += 1
                dia["items"][iid] = p2
                continue
            if "prov" in p2 and p2["prov"] != (antes.get("prov") or ""):
                log.append({"a": "providencia", **base})
                p2["respProv"] = user.id
            if "eq" in p2 and p2["eq"] != antes.get("eq") and p2.get("eqAuto") is not True:
                log.append({"a": "equipe", **base})
            if "st" in p2 and p2["st"] != (antes.get("st") or "pendente"):
                if p2.get("baixa"):
                    log.append({"a": "baixa", **base, "u": antes.get("respProv"), "por": user.id})
                else:
                    log.append({"a": "cumprido" if p2["st"] == "cumprido" else "reaberto", **base})
            if "edOk" in p2 and p2["edOk"] and not antes.get("edOk"):
                log.append({"a": "ed", **base})
            if "obs" in p2 and p2["obs"] != (antes.get("obs") or ""):
                log.append({"a": "obs", **base})
            if origem == "manual" or log:
                p2["by"], p2["at"] = user.id, agora
            antes.update(p2)
        if novos:
            log.append({"t": agora, "u": user.id, "d": d, "a": "importacao", "n": novos})
        L.registrar(log)
        L.gravar()
        return {"ok": True, "rev": L.estado["rev"]}


@router.post("/apagar")
async def apagar(request: Request, user=Depends(prazos_user)):
    if not _admin(user):
        raise HTTPException(403, "Somente o administrador apaga prazos em lote.")
    corpo = await _corpo(request)
    lote = corpo.get("lote") if isinstance(corpo, dict) else None
    if not isinstance(lote, dict):
        raise HTTPException(400, "lote ausente")
    L = loja()
    with L.trava:
        L._copia("prazos-antes-apagar-" + datetime.now(FUSO).strftime("%Y-%m-%d_%H%M%S") + ".json")
        n = 0
        for d, ids in lote.items():
            dia = L.estado["dias"].get(d)
            if not dia:
                continue
            if ids == "*":
                n += sum(1 for x in dia["items"].values() if x and x.get("proc"))
                del L.estado["dias"][d]
                continue
            if not isinstance(ids, list):
                continue
            for i in ids:
                if isinstance(i, str) and dia["items"].get(i):
                    dia["items"][i] = None
                    n += 1
        L.registrar([{"t": _agora(), "u": user.id, "a": "apagar_lote", "n": n}])
        L.gravar()
        return {"ok": True, "n": n, "rev": L.estado["rev"]}


@router.put("/config")
async def config(request: Request, user=Depends(prazos_user)):
    if not pode(user, "configurar"):
        raise HTTPException(403, "Você não tem permissão para alterar configurações.")
    cfg = _limpa_config(await _corpo(request))
    L = loja()
    with L.trava:
        L.estado["config"] = cfg
        L.registrar([{"t": _agora(), "u": user.id, "a": "config"}])
        L.gravar()
        return {"ok": True, "rev": L.estado["rev"]}


def _produtividade(L: Loja, de: str | None, ate: str | None) -> dict:
    por = {}
    campos = {"providencia": "providencias", "equipe": "equipes", "cumprido": "cumpridos", "reaberto": "reabertos",
              "ed": "ed", "obs": "obs", "exclusao": "exclusoes", "baixa": "baixas"}
    try:
        linhas = open(L.log, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        linhas = []
    for linha in linhas:
        try:
            r = json.loads(linha)
            dia = datetime.fromisoformat(str(r.get("t", "")).replace("Z", "+00:00")).astimezone(FUSO).date().isoformat()
        except (ValueError, TypeError):
            continue
        if (de and dia < de) or (ate and dia > ate):
            continue
        o = por.setdefault(r.get("u") or "?", {"providencias": 0, "equipes": 0, "cumpridos": 0, "reabertos": 0, "ed": 0, "obs": 0,
                                               "exclusoes": 0, "importacoes": 0, "prazosImportados": 0, "baixas": 0, "total": 0,
                                               "ultima": ""})
        a = r.get("a")
        if a in campos:
            o[campos[a]] += 1
        elif a == "importacao":
            o["importacoes"] += 1
            o["prazosImportados"] += int(r.get("n") or 0)
        if a != "baixa":
            o["total"] += 1
            if r.get("t", "") > o["ultima"]:
                o["ultima"] = r["t"]
    return por


@router.get("/produtividade")
def produtividade(de: str | None = None, ate: str | None = None, user=Depends(prazos_user), db=Depends(get_db)):
    if not pode(user, "relatorio"):
        raise HTTPException(403, "Sem permissão para ver a produtividade.")
    return {"por": _produtividade(loja(), de, ate), "usuarios": [publico(x) for x in db.scalars(select(User).order_by(User.name))]}


def importar_arquivo(caminho: str) -> str:
    """Traz o prazos.json do sistema antigo (Node). Só aceita se o THANOS ainda não tiver prazos."""
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    if not isinstance(dados, dict) or not isinstance(dados.get("dias"), dict):
        raise SystemExit("Arquivo não parece ser o prazos.json do sistema de prazos")
    L = loja()
    with L.trava:
        if any(v and any(v.get("items", {}).values()) for v in L.estado["dias"].values()):
            raise SystemExit("O THANOS já tem prazos cadastrados. Para não misturar, a importação só é feita com o módulo vazio.")
        dias = {}
        for d, dia in dados["dias"].items():
            if not DIA_RX.match(d) or not isinstance(dia, dict):
                continue
            itens = {}
            for iid, it in (dia.get("items") or {}).items():
                if it and ID_RX.match(str(iid)):
                    limpo = _limpa_item(it, so_tela=False)
                    if isinstance(it.get("at"), str):  # "by"/"respProv" ficam de fora: eram do cadastro de usuários antigo
                        limpo["at"] = it["at"][:40]
                    if limpo.get("proc"):
                        itens[iid] = limpo
            if itens:
                dias[d] = {"data": d, "items": itens}
        L.estado["dias"] = dias
        if isinstance(dados.get("config"), dict):
            try:
                L.estado["config"] = _limpa_config(dados["config"])
            except HTTPException as e:
                raise SystemExit(f"Configuração do arquivo inválida: {e.detail}")
        L.registrar([{"t": _agora(), "u": "importacao-inicial", "a": "migracao", "n": sum(len(x["items"]) for x in dias.values())}])
        L.gravar()
        return f"{sum(len(x['items']) for x in dias.values())} prazos importados em {len(dias)} datas."
