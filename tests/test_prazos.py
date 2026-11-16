"""Módulo amarelo (Controle de Prazos) dentro do THANOS: mesmo login, mesmas permissões, regras do sistema antigo."""
import json, os
import pytest
from fastapi.testclient import TestClient
from tests.conftest import login

DIA = "2026-11-20"
ITEM = {"proc": "5001234-56.2024.4.04.7205", "cliente": "Cliente Teste", "cpf": "00000000000", "trib": "JFSC", "eq": 2,
        "eqAuto": True, "st": "pendente", "prov": "", "obs": "", "dias": 15, "classe": "Procedimento Comum", "assunto": "X"}


def _set(env, email, **kw):
    from app.db import SessionLocal
    from app.models import User
    from sqlalchemy import select
    s = SessionLocal()
    u = s.scalar(select(User).where(User.email == email))
    for k, v in kw.items():
        setattr(u, k, v)
    s.commit(); s.close()


@pytest.fixture()
def admin(env):
    _set(env, "a@x.com", role="admin")
    from app.main import app
    c = login(TestClient(app), "a@x.com", "senha-segura-1")
    sess = c.get("/prazos/api/sessao").json()
    c.headers["X-CSRF-Token"] = sess["csrf"]
    return c


def _importa(c, items=None):
    return c.post(f"/prazos/api/dias/{DIA}", json={"origem": "importacao", "items": items or {"p1": dict(ITEM)}})


def test_pagina_exige_login(env):
    from app.main import app
    c = TestClient(app)
    r = c.get("/prazos/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?next=/prazos/"
    assert c.get("/prazos/api/estado").status_code == 401
    assert c.get("/prazos/api/sessao").json()["usuario"] is None


def test_pagina_e_csp(admin):
    r = admin.get("/prazos/")
    assert r.status_code == 200 and "Controle de Prazos" in r.text
    assert "cdn.jsdelivr" not in r.text  # leitor de planilhas servido pelo próprio servidor
    assert "script-src 'self' 'unsafe-inline'" in r.headers["content-security-policy"]
    assert admin.get("/prazos/vendor/xlsx.bundle.js").status_code == 200


def test_importa_e_le(admin):
    assert _importa(admin).status_code == 200
    st = admin.get("/prazos/api/estado").json()
    it = st["dias"][DIA]["items"]["p1"]
    assert it["cliente"] == "Cliente Teste" and st["rev"] >= 2


def test_csrf_obrigatorio(admin):
    admin.headers.pop("X-CSRF-Token")
    assert _importa(admin).status_code == 403


def test_campos_estranhos_e_tipos_sao_limpos(admin):
    item = dict(ITEM, dias="<img src=x onerror=alert(1)>", eq="2", hack="x", __proto__={"a": 1})
    _importa(admin, {"p1": item})
    it = admin.get("/prazos/api/estado").json()["dias"][DIA]["items"]["p1"]
    assert it["dias"] is None and it["eq"] is None and "hack" not in it and "__proto__" not in it


def test_padrao_ve_e_lanca_providencia_mas_nao_importa(admin, cb):
    _importa(admin)
    st = cb.get("/prazos/api/sessao").json()
    assert st["usuario"]["perms"]["exportar"] and not st["usuario"]["perms"]["importar"]
    cb.headers["X-CSRF-Token"] = st["csrf"]
    assert _importa(cb).status_code == 403
    # sem equipe definida, a pessoa lança providência (como no sistema antigo)
    r = cb.post(f"/prazos/api/dias/{DIA}", json={"items": {"p1": {"prov": "réplica"}}})
    assert r.status_code == 200
    it = admin.get("/prazos/api/estado").json()["dias"][DIA]["items"]["p1"]
    assert it["prov"] == "réplica" and it["respProv"] and it["by"]


def test_tela_nao_altera_dados_do_processo(admin, cb, env):
    _importa(admin)
    cb.headers["X-CSRF-Token"] = cb.get("/prazos/api/sessao").json()["csrf"]
    cb.post(f"/prazos/api/dias/{DIA}", json={"items": {"p1": {"prov": "ok", "cliente": "Outro", "proc": "1", "baixa": "2026"}}})
    it = admin.get("/prazos/api/estado").json()["dias"][DIA]["items"]["p1"]
    assert it["cliente"] == "Cliente Teste" and it["proc"] == ITEM["proc"] and not it.get("baixa")


def test_outra_equipe_bloqueada(admin, env):
    _importa(admin)
    _set(env, "b@x.com", prazos_equipe=1)
    from app.main import app
    cb = login(TestClient(app), "b@x.com", "senha-segura-2")
    cb.headers["X-CSRF-Token"] = cb.get("/prazos/api/sessao").json()["csrf"]
    r = cb.post(f"/prazos/api/dias/{DIA}", json={"items": {"p1": {"prov": "x"}}})
    assert r.status_code == 403 and "outra equipe" in r.json()["detail"]
    assert cb.post(f"/prazos/api/dias/{DIA}", json={"items": {"p1": None}}).status_code == 403
    assert cb.post("/prazos/api/apagar", json={"lote": {DIA: "*"}}).status_code == 403
    assert cb.put("/prazos/api/config", json={}).status_code == 403
    assert cb.get("/prazos/api/produtividade").status_code == 403
    # o administrador libera pela tela de usuários do THANOS
    _set(env, "b@x.com", perms={"prazos": True, "prazos_editar_outra": True})
    assert cb.post(f"/prazos/api/dias/{DIA}", json={"items": {"p1": {"prov": "x"}}}).status_code == 200


def test_sem_acesso_ao_modulo(admin, env):
    _set(env, "b@x.com", perms={"prazos": False})
    from app.main import app
    cb = login(TestClient(app), "b@x.com", "senha-segura-2")
    assert cb.get("/prazos/api/sessao").json().get("semAcesso") is True
    assert cb.get("/prazos/api/estado").status_code == 403


def test_link_de_tribunal_so_https(admin):
    assert admin.put("/prazos/api/config", json={"links": {"JFSC": "javascript:alert(1)"}}).status_code == 400
    assert admin.put("/prazos/api/config", json={"links": {"JFSC": "https://eproc.jfsc.jus.br/"}, "regras": []}).status_code == 200
    assert admin.put("/prazos/api/config", json={"regras": "x"}).status_code == 400


def test_backup_antes_de_apagar_e_do_dia(admin, env, tmp_path):
    _importa(admin)
    _importa(admin, {"p2": dict(ITEM, proc="5000000-00.2024.4.04.7205")})
    r = admin.post("/prazos/api/apagar", json={"lote": {DIA: "*"}})
    assert r.json()["n"] == 2
    bk = os.listdir(tmp_path / "prazos" / "backup")
    antes = [f for f in bk if f.startswith("prazos-antes-apagar-")]
    assert antes
    salvo = json.load(open(tmp_path / "prazos" / "backup" / antes[0]))
    assert len(salvo["dias"][DIA]["items"]) == 2  # a cópia tem os prazos de antes da exclusão


def test_produtividade(admin):
    _importa(admin)
    admin.post(f"/prazos/api/dias/{DIA}", json={"items": {"p1": {"prov": "réplica", "st": "cumprido"}}})
    j = admin.get("/prazos/api/produtividade").json()
    me = [u for u in j["usuarios"] if u["admin"]][0]["id"]
    assert j["por"][me]["providencias"] == 1 and j["por"][me]["cumpridos"] == 1 and j["por"][me]["prazosImportados"] == 1


def test_importar_arquivo_antigo(env, tmp_path):
    from app.prazos_api import importar_arquivo, loja
    arq = tmp_path / "antigo.json"
    arq.write_text(json.dumps({"dias": {DIA: {"data": DIA, "items": {"p1": dict(ITEM, by="u123"), "p0": None}}},
                               "config": {"nomes": {"1": "Equipe Beta", "2": "Equipe Alfa"}, "links": {}}, "rev": 9}))
    assert "1 prazos" in importar_arquivo(str(arq))
    assert "by" not in loja().estado["dias"][DIA]["items"]["p1"]
    with pytest.raises(SystemExit):
        importar_arquivo(str(arq))  # não mistura com prazos já existentes


def test_trocar_a_propria_senha(ca):
    r = ca.post("/api/minha-senha", json={"atual": "errada-123456", "nova": "nova-senha-123"})
    assert r.status_code == 400
    assert ca.post("/api/minha-senha", json={"atual": "senha-segura-1", "nova": "curta1"}).status_code == 400
    assert ca.post("/api/minha-senha", json={"atual": "senha-segura-1", "nova": "nova-senha-123"}).status_code == 200
    from app.main import app
    login(TestClient(app), "a@x.com", "nova-senha-123")


def test_equipe_pela_tela_de_usuarios(admin, env):
    cat = admin.get("/api/admin/permissions").json()
    assert any(p["key"] == "prazos_importar" and "Prazos" in p["group"] for p in cat["perms"])
    users = admin.get("/api/admin/users").json()
    b = [u for u in users if u["email"] == "b@x.com"][0]
    r = admin.patch(f"/api/admin/users/{b['id']}", json={"prazos_equipe": 2})
    assert r.json()["prazos_equipe"] == 2
    assert admin.patch(f"/api/admin/users/{b['id']}", json={"prazos_equipe": 7}).status_code == 400
