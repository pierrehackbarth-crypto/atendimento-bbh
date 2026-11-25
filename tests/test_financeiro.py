"""Módulo verde (Financeiro – RPV Bancos) dentro do THANOS: mesmo login, permissões por pessoa, dados no servidor."""
import pytest
from fastapi.testclient import TestClient
from tests.conftest import login

PDF = b"%PDF-1.4\n% teste\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
MES = {"mes": "11.2026", "rotulo": "NOVEMBRO DE 2026", "dataPedido": {"dia": "24", "mes": "novembro", "ano": "2026"},
       "lev": [{"banco": "BB", "cliente": "CLIENTE FICTICIO", "filial": "timb", "originario": "5000000-00.2024.4.04.7205",
                "rpv": "5000001-00.2026.4.04.9999", "tipo": "Honorários contratuais", "valor": 1234.56, "conta": "1234567890", "pag": [0, 2]}],
       "pend": [], "cont": {"BB": [{"nome": "CLIENTE FICTICIO", "cpf": "000.000.000-00", "capital": 1234.56, "ir": 37.04,
                                   "tarifa": 0, "data": "24/11/2026", "obs": "", "conferir": ""}], "CEF": []},
       "lixo": "<script>"}


def _set(email, **kw):
    from app.db import SessionLocal
    from app.models import User
    from sqlalchemy import select
    s = SessionLocal()
    u = s.scalar(select(User).where(User.email == email))
    for k, v in kw.items():
        setattr(u, k, v)
    s.commit(); s.close()


def _cliente(email, pw):
    from app.main import app
    return login(TestClient(app), email, pw)  # o login já traz o token CSRF da sessão


@pytest.fixture()
def admin(env):
    _set("a@x.com", role="admin")
    return _cliente("a@x.com", "senha-segura-1")


def _importa(c, mes=MES):
    up = c.post("/financeiro/api/arquivos", content=PDF, headers={"Content-Type": "application/pdf"})
    assert up.status_code == 200, up.text
    doc = {**mes, "arquivos": {"bb": up.json(), "cef": {}}, "conferidos": []}
    return c.put("/financeiro/api/meses/2026-11", json=doc), up.json()


def test_pagina_exige_login(env):
    from app.main import app
    c = TestClient(app)
    r = c.get("/financeiro/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?next=/financeiro/"
    assert c.get("/financeiro/api/meses").status_code == 401
    assert c.get("/financeiro/api/sessao").json()["usuario"] is None


def test_fechado_por_padrao(env):
    c = _cliente("b@x.com", "senha-segura-2")  # advogado sem ajuste: o Financeiro vem fechado
    assert c.get("/financeiro/", follow_redirects=False).status_code == 403
    assert c.get("/financeiro/api/sessao").json()["semAcesso"] is True
    assert c.get("/financeiro/api/meses").status_code == 403
    assert "financeiro" not in [k for k, v in c.get("/api/me").json()["user"]["perms"].items() if v]


def test_pagina_csp_e_scripts_locais(admin):
    r = admin.get("/financeiro/")
    assert r.status_code == 200 and "RPV BANCOS" in r.text
    assert "cdnjs" not in r.text
    assert "script-src 'self';" in r.headers["content-security-policy"]
    for f in ("app.js", "adaptador.js", "jszip.min.js", "pdf-lib.min.js"):
        assert admin.get("/financeiro/web/" + f).status_code == 200


def test_importa_le_e_baixa_pdf(admin):
    r, up = _importa(admin)
    assert r.status_code == 200, r.text
    m = admin.get("/financeiro/api/meses").json()["meses"]["2026-11"]
    assert m["lev"][0]["cliente"] == "CLIENTE FICTICIO" and "lixo" not in m
    assert m["arquivos"]["bb"]["url"] == f"/financeiro/api/arquivos/{up['id']}"
    pdf = admin.get(m["arquivos"]["bb"]["url"])
    assert pdf.status_code == 200 and pdf.content == PDF and pdf.headers["content-type"] == "application/pdf"


def test_recusa_mes_errado_e_nao_pdf(admin):
    up = admin.post("/financeiro/api/arquivos", content=b"<html>", headers={"Content-Type": "application/pdf"})
    assert up.status_code == 400
    r = admin.put("/financeiro/api/meses/2026-10", json={**MES})
    assert r.status_code == 400  # o pacote é de 11.2026
    assert admin.put("/financeiro/api/meses/..%2Fx", json=MES).status_code in (404, 405)
    falso = {**MES, "arquivos": {"bb": {"id": "0" * 32, "url": "https://outro.site/x.pdf"}}}
    assert admin.put("/financeiro/api/meses/2026-11", json=falso).status_code == 400


def test_conferir_e_ajustar(admin):
    _importa(admin)
    cont = {"BB": [{**MES["cont"]["BB"][0], "ir": 0}], "CEF": []}
    r = admin.patch("/financeiro/api/meses/2026-11", json={"conferidos": ["BB:1234567890:x"], "cont": cont, "lev": []})
    assert r.status_code == 200
    m = admin.get("/financeiro/api/meses").json()["meses"]["2026-11"]
    assert m["conferidos"] == ["BB:1234567890:x"] and m["cont"]["BB"][0]["ir"] == 0
    assert len(m["lev"]) == 1  # a tela não troca os levantamentos depois de importar


def test_pdf_em_uso_nao_e_apagado(admin):
    _, up = _importa(admin)
    assert admin.delete(f"/financeiro/api/arquivos/{up['id']}").json()["emUso"] is True
    assert admin.get(up["url"]).status_code == 200
    r, up2 = _importa(admin)  # reimportar: o PDF antigo deixa de ser usado e pode ser apagado
    assert admin.delete(f"/financeiro/api/arquivos/{up['id']}").json()["ok"] is True
    assert admin.get(up["url"]).status_code == 404 and admin.get(up2["url"]).status_code == 200


def test_permissoes_por_pessoa(admin, env):
    _importa(admin)
    _set("b@x.com", perms={"financeiro": True})
    so_ver = _cliente("b@x.com", "senha-segura-2")
    assert so_ver.get("/financeiro/").status_code == 200
    assert so_ver.get("/financeiro/api/sessao").json()["usuario"]["perms"] == {"importar": False, "editar": False}
    assert "2026-11" in so_ver.get("/financeiro/api/meses").json()["meses"]
    assert so_ver.patch("/financeiro/api/meses/2026-11", json={"conferidos": []}).status_code == 403
    assert so_ver.post("/financeiro/api/arquivos", content=PDF, headers={"Content-Type": "application/pdf"}).status_code == 403
    _set("b@x.com", perms={"financeiro": True, "financeiro_editar": True})
    assert so_ver.patch("/financeiro/api/meses/2026-11", json={"conferidos": ["x"]}).status_code == 200


def test_csrf_obrigatorio(admin):
    del admin.headers["X-CSRF-Token"]
    assert admin.post("/financeiro/api/arquivos", content=PDF, headers={"Content-Type": "application/pdf"}).status_code == 403


def test_grupo_na_tela_de_usuarios(admin):
    cat = admin.get("/api/admin/permissions").json()
    grupos = {p["key"]: p["group"] for p in cat["perms"]}
    assert grupos["financeiro_importar"] == "Financeiro (joia verde)"
