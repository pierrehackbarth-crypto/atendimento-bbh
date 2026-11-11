"""Importação de dados para a ficha no servidor próprio.

Aceita:
- o arquivo do botão "Exportar backup" da ficha ({"tipo":"fichas-atendimento-backup", "fichas":[...], "lixeira":[...]});
- a base de clientes exportada do claude.ai ({"tipo":"base-clientes-ficha", "clientes":{id:{l:[...]}}, "nomes":{id:{l:[...]}}}),
  em .json ou .json.gz.
Fichas só entram se não existirem ou se a versão do arquivo for mais nova; nada é apagado.
"""
import gzip, json
from .models import StoreDoc
from .ficha_api import _bump


def _load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _put(db, col, doc_id, data, only_if_newer=False):
    r = db.get(StoreDoc, (col, doc_id))
    if r and only_if_newer and (r.data.get("updatedAt") or 0) >= (data.get("updatedAt") or 0):
        return False
    if r:
        r.data = data
    else:
        db.add(StoreDoc(collection=col, doc_id=doc_id, data=data, updated_by=None))
    return True


def import_file(db, path):
    o = _load(path)
    tipo = o.get("tipo")
    out = {}
    if tipo == "fichas-atendimento-backup":
        for col in ("fichas", "lixeira"):
            n = 0
            for f in o.get(col) or []:
                f = dict(f)
                doc_id = str(f.pop("id", "") or "")
                if doc_id and _put(db, col, doc_id, f, only_if_newer=True):
                    n += 1
            if n:
                _bump(db, col)
            out[col] = n
    elif tipo == "base-clientes-ficha":
        for col in ("clientes", "nomes"):
            docs = o.get(col) or {}
            for doc_id, data in docs.items():
                _put(db, col, str(doc_id), data)
            _bump(db, col)
            out[col] = len(docs)
        out["clientes_total"] = sum(len(d.get("l") or []) for d in (o.get("clientes") or {}).values())
    else:
        raise SystemExit("Arquivo não reconhecido: esperado backup da ficha ou base de clientes")
    db.commit()
    return out
