"""THANOS – módulo VERDE (Financeiro), primeira ferramenta: RPV BANCOS.

Traz para dentro do THANOS a página "RPV BANCOS" (pasta E:\\BRUNA\\RPV_BANCOS): pedidos de levantamento de RPVs
no Banco do Brasil e na Caixa e a prévia da planilha mensal da Contabilidade.

O motor em Python (GERAR RPV BANCOS / GERAR CONTABILIDADE) continua rodando no computador onde estão as pastas
dos meses e gera o "RPV BANCOS - MM.AAAA.zip". A página importa esse pacote, e o mês fica guardado AQUI, no
servidor, com o mesmo login e as mesmas permissões por pessoa do THANOS.

Os dados ficam em data/financeiro/ (dentro da pasta que já entra na cópia de segurança diária):
  meses/AAAA-MM.json ...... um registro por mês (levantamentos, pendências, contabilidade, conferências)
  arquivos/<id>.pdf ....... PDFs do mês (formulários do BB num PDF único, cartas da Caixa)
  backup/ ................. cópia do mês antes de cada nova importação (guarda as 60 mais recentes)
  atividade.jsonl ......... quem importou, conferiu ou ajustou o quê
"""
import json, os, re, secrets, shutil, threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from .config import get_settings
from .models import User
from .security import get_db, current_user, optional_user
from .permissions import has

router = APIRouter(prefix="/financeiro/api")
FUSO = ZoneInfo("America/Sao_Paulo")
MES_RX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ARQ_RX = re.compile(r"^[a-f0-9]{32}$")
MAX_MES = 10 * 1024 * 1024       # um mês em JSON (centenas de linhas cabem com folga)
MAX_PDF = 40 * 1024 * 1024       # o PDF único do BB junta todos os formulários e demonstrativos
CAMPOS_MES = {"mes", "rotulo", "dataPedido", "geradoEm", "lidos", "lev", "pend", "cont", "arquivos", "conferidos",
              "importadoEm"}
CAMPOS_EDITAVEIS = {"conferidos", "cont"}   # o que a tela muda depois de importar


def _pasta() -> str:
    p = os.path.abspath(get_settings().financeiro_dir)
    for sub in ("meses", "arquivos", "backup"):
        os.makedirs(os.path.join(p, sub), exist_ok=True)
    return p


_trava = threading.RLock()


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _registrar(user: User, acao: str, **extra):
    with open(os.path.join(_pasta(), "atividade.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": _agora(), "u": user.id, "a": acao, **extra}, ensure_ascii=False) + "\n")


def _arq_mes(mid: str) -> str:
    if not MES_RX.match(mid):
        raise HTTPException(404, "Mês inválido")
    return os.path.join(_pasta(), "meses", mid + ".json")


def _ler(mid: str) -> dict | None:
    a = _arq_mes(mid)
    if not os.path.exists(a):
        return None
    with open(a, encoding="utf-8") as f:
        return json.load(f)


def _gravar(mid: str, doc: dict):
    a = _arq_mes(mid)
    tmp = a + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, a)


def _url(aid: str) -> str:
    return f"/financeiro/api/arquivos/{aid}"


def _limpa_ref(r) -> dict | None:
    """Referência a um PDF guardado: só o id conta; o endereço é sempre o do servidor."""
    if not isinstance(r, dict) or not ARQ_RX.match(str(r.get("id") or "")):
        return None
    if not os.path.exists(os.path.join(_pasta(), "arquivos", r["id"] + ".pdf")):
        raise HTTPException(400, "PDF do mês não encontrado no servidor. Importe de novo.")
    return {"id": r["id"], "url": _url(r["id"])}


def _limpa_mes(mid: str, doc, parcial: bool) -> dict:
    if not isinstance(doc, dict):
        raise HTTPException(400, "Dados do mês inválidos")
    if len(json.dumps(doc, ensure_ascii=False)) > MAX_MES:
        raise HTTPException(413, "Mês grande demais")
    permitidos = CAMPOS_EDITAVEIS if parcial else CAMPOS_MES
    out = {k: v for k, v in doc.items() if k in permitidos}
    if not parcial:
        mes = str(out.get("mes") or "")
        m = re.match(r"^(\d{2})\.(\d{4})$", mes)
        if not m or f"{m.group(2)}-{m.group(1)}" != mid:
            raise HTTPException(400, "O pacote não é deste mês")
        for k, t in (("lev", list), ("pend", list)):
            if not isinstance(out.get(k), t):
                raise HTTPException(400, f"Pacote do mês sem '{k}'")
        arq = out.get("arquivos") or {}
        if not isinstance(arq, dict):
            raise HTTPException(400, "Arquivos do mês inválidos")
        cef = arq.get("cef") if isinstance(arq.get("cef"), dict) else {}
        out["arquivos"] = {"cef": {str(n)[:3]: r for n, r in ((n, _limpa_ref(r)) for n, r in cef.items()) if r}}
        bb = _limpa_ref(arq.get("bb"))
        if bb:
            out["arquivos"]["bb"] = bb
    if "conferidos" in out:
        if not isinstance(out["conferidos"], list):
            raise HTTPException(400, "Conferidos inválidos")
        out["conferidos"] = [str(x)[:200] for x in out["conferidos"][:5000]]
    if "cont" in out:
        c = out["cont"]
        if not isinstance(c, dict) or not all(isinstance(c.get(b, []), list) for b in ("BB", "CEF")):
            raise HTTPException(400, "Contabilidade inválida")
        out["cont"] = {"BB": c.get("BB", []), "CEF": c.get("CEF", [])}
    return out


def _refs(doc: dict | None) -> set:
    if not doc:
        return set()
    a = doc.get("arquivos") or {}
    ids = {r.get("id") for r in (a.get("cef") or {}).values() if isinstance(r, dict)}
    if isinstance(a.get("bb"), dict):
        ids.add(a["bb"].get("id"))
    return {i for i in ids if i and ARQ_RX.match(i)}


def _apaga_arquivo(aid: str):
    try:
        os.remove(os.path.join(_pasta(), "arquivos", aid + ".pdf"))
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- permissões
def fin_user(user: User = Depends(current_user)) -> User:
    if not has(user, "financeiro"):
        raise HTTPException(403, "Seu usuário não tem acesso ao Financeiro. Peça ao administrador.")
    return user


def _exige(user: User, perm: str, oque: str):
    if not has(user, perm):
        raise HTTPException(403, f"Você não tem permissão para {oque}.")


async def _json(request: Request, limite=MAX_MES):
    if int(request.headers.get("content-length") or 0) > limite:
        raise HTTPException(413, "Dados grandes demais")
    try:
        return await request.json()
    except ValueError:
        raise HTTPException(400, "Dados inválidos")


# ---------------------------------------------------------------- rotas
@router.get("/sessao")
def sessao(request: Request, db=Depends(get_db)):
    u = optional_user(request, db)
    if not u:
        return {"usuario": None, "login": "/?next=/financeiro/"}
    if not has(u, "financeiro"):
        return {"usuario": None, "semAcesso": True, "nome": u.name}
    from .security import _th, COOKIE
    from .models import SessionToken
    st = db.get(SessionToken, _th(request.cookies.get(COOKIE, "")))
    return {"usuario": {"id": u.id, "nome": u.name, "admin": u.role == "admin",
                        "perms": {"importar": has(u, "financeiro_importar"), "editar": has(u, "financeiro_editar")}},
            "csrf": st.csrf if st else ""}


@router.get("/meses")
def meses(user=Depends(fin_user)):
    out = {}
    pasta = os.path.join(_pasta(), "meses")
    for nome in sorted(os.listdir(pasta)):
        mid = nome[:-5]
        if nome.endswith(".json") and MES_RX.match(mid):
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                out[mid] = json.load(f)
    return {"meses": out}


@router.put("/meses/{mid}")
async def gravar_mes(mid: str, request: Request, user=Depends(fin_user)):
    _exige(user, "financeiro_importar", "importar meses")
    doc = _limpa_mes(mid, await _json(request), parcial=False)
    doc["importadoEm"], doc["importadoPor"] = _agora(), user.id
    doc.setdefault("conferidos", [])
    with _trava:
        antigo = _ler(mid)
        if antigo:
            shutil.copy2(_arq_mes(mid), os.path.join(_pasta(), "backup",
                                                     f"{mid}-antes-{datetime.now(FUSO).strftime('%Y-%m-%d_%H%M%S')}.json"))
            velhos = sorted(os.listdir(os.path.join(_pasta(), "backup")))
            for v in velhos[:-60]:
                os.remove(os.path.join(_pasta(), "backup", v))
        _gravar(mid, doc)
        _registrar(user, "importacao", mes=mid, contas=len(doc.get("lev") or []))
    return {"ok": True}


@router.patch("/meses/{mid}")
async def alterar_mes(mid: str, request: Request, user=Depends(fin_user)):
    _exige(user, "financeiro_editar", "conferir e ajustar os lançamentos")
    campos = _limpa_mes(mid, await _json(request), parcial=True)
    if not campos:
        raise HTTPException(400, "Nada para gravar")
    with _trava:
        doc = _ler(mid)
        if doc is None:
            raise HTTPException(404, "Mês não importado")
        doc.update(campos)
        doc["alteradoEm"], doc["alteradoPor"] = _agora(), user.id
        _gravar(mid, doc)
        _registrar(user, "alteracao", mes=mid, campos=sorted(campos))
    return {"ok": True}


@router.post("/arquivos")
async def guardar_pdf(request: Request, user=Depends(fin_user)):
    _exige(user, "financeiro_importar", "importar meses")
    if int(request.headers.get("content-length") or 0) > MAX_PDF:
        raise HTTPException(413, "PDF grande demais")
    corpo = await request.body()
    if len(corpo) > MAX_PDF:
        raise HTTPException(413, "PDF grande demais")
    if not corpo.startswith(b"%PDF-"):
        raise HTTPException(400, "O arquivo não é um PDF")
    aid = secrets.token_hex(16)
    destino = os.path.join(_pasta(), "arquivos", aid + ".pdf")
    with open(destino + ".tmp", "wb") as f:
        f.write(corpo)
    os.replace(destino + ".tmp", destino)
    return {"id": aid, "url": _url(aid), "sizeBytes": len(corpo), "contentType": "application/pdf"}


@router.delete("/arquivos/{aid}")
def apagar_pdf(aid: str, user=Depends(fin_user)):
    _exige(user, "financeiro_importar", "importar meses")
    if not ARQ_RX.match(aid):
        raise HTTPException(404, "Arquivo não encontrado")
    with _trava:  # nunca apaga um PDF que algum mês salvo ainda usa
        pasta = os.path.join(_pasta(), "meses")
        for nome in os.listdir(pasta):
            if nome.endswith(".json") and MES_RX.match(nome[:-5]) and aid in _refs(_ler(nome[:-5])):
                return {"ok": False, "emUso": True}
        _apaga_arquivo(aid)
    return {"ok": True}


@router.get("/arquivos/{aid}")
def ler_pdf(aid: str, user=Depends(fin_user)):
    if not ARQ_RX.match(aid):
        raise HTTPException(404, "Arquivo não encontrado")
    a = os.path.join(_pasta(), "arquivos", aid + ".pdf")
    if not os.path.exists(a):
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(a, media_type="application/pdf", headers={"Cache-Control": "no-store"})
