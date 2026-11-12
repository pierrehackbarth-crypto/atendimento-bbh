"""Controle de usuários e permissões definidas pelo administrador."""
import pytest
from tests.conftest import login


@pytest.fixture()
def cadm(env):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password
    s = SessionLocal()
    s.add(User(email="adm@x.com", name="Admin", role="admin", password_hash=hash_password("senha-admin-123")))
    s.commit(); s.close()
    return login(TestClient(app), "adm@x.com", "senha-admin-123")


def test_only_admin_manages_users(ca, cadm, env):
    assert ca.get("/api/admin/users").status_code == 403
    assert ca.post("/api/admin/users", json={"email": "z@x.com", "name": "Z", "password": "x" * 12}).status_code == 403
    r = cadm.get("/api/admin/users")
    assert r.status_code == 200 and {u["email"] for u in r.json()} >= {"a@x.com", "b@x.com", "adm@x.com"}


def test_create_user_and_password_rules(cadm, env):
    assert cadm.post("/api/admin/users", json={"email": "c@x.com", "name": "C", "password": "curta"}).status_code == 400
    r = cadm.post("/api/admin/users", json={"email": "C@x.com", "name": "Estagiária C", "role": "assistente", "password": "senha-forte-99"})
    assert r.status_code == 200
    u = r.json()
    assert u["email"] == "c@x.com" and u["perms"]["fichas_excluir"] is False and u["perms"]["fichas_editar"] is True
    assert cadm.post("/api/admin/users", json={"email": "c@x.com", "name": "C", "password": "senha-forte-99"}).status_code == 409


def test_permissions_enforced_on_ficha(ca, cb, cadm, env):
    ca.put("/api/ficha/db/fichas/fa", json={"criadoPor": env["a"], "d": {"nome": "DE A"}})
    cb.put("/api/ficha/db/fichas/fb", json={"criadoPor": env["b"], "d": {"nome": "DE B"}})
    # B só vê as próprias fichas, não exclui, não usa IA nem a base de clientes
    perms = {"fichas_ver": True, "fichas_todas": False, "fichas_editar": True, "fichas_excluir": False,
             "lixeira": False, "base_clientes": False, "ia": False, "gravacao": False}
    assert cadm.patch(f"/api/admin/users/{env['b']}", json={"perms": perms}).status_code == 200
    assert [d["id"] for d in cb.get("/api/ficha/db/fichas").json()["docs"]] == ["fb"]
    assert cb.get("/api/ficha/db/fichas/fa").status_code == 403
    assert cb.put("/api/ficha/db/fichas/fa", json={"d": {"nome": "MEXI"}}).status_code == 403
    assert cb.delete("/api/ficha/db/fichas/fb").status_code == 403
    assert cb.put("/api/ficha/db/lixeira/fb", json={"d": {}}).status_code == 403
    assert cb.get("/api/ficha/db/lixeira").json()["docs"] == []
    assert cb.get("/api/ficha/db/nomes").status_code == 403
    assert cb.post("/api/ficha/ai", data={"input": "x", "json": "0"}).status_code == 403
    assert cb.get("/api/clients").status_code == 403          # módulo de gravação
    me = cb.get("/api/ficha/me").json()
    assert me["perms"]["fichas_todas"] is False and me["perms"]["ia"] is False
    # A (padrão de advogado) segue vendo tudo
    assert {d["id"] for d in ca.get("/api/ficha/db/fichas").json()["docs"]} == {"fa", "fb"}
    # voltar ao padrão do papel devolve o acesso
    cadm.patch(f"/api/admin/users/{env['b']}", json={"reset_perms": True})
    assert {d["id"] for d in cb.get("/api/ficha/db/fichas").json()["docs"]} == {"fa", "fb"}


def test_block_and_password_reset_end_sessions(cb, cadm, env):
    assert cb.get("/api/ficha/me").status_code == 200
    cadm.patch(f"/api/admin/users/{env['b']}", json={"active": False})
    assert cb.get("/api/ficha/me").status_code == 401
    cadm.patch(f"/api/admin/users/{env['b']}", json={"active": True})
    cadm.post(f"/api/admin/users/{env['b']}/password", json={"password": "nova-senha-123"})
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).post("/api/login", json={"email": "b@x.com", "password": "senha-segura-2"}).status_code == 401
    login(TestClient(app), "b@x.com", "nova-senha-123")


def test_last_admin_cannot_be_removed(cadm, env):
    me = cadm.get("/api/me").json()["user"]
    assert cadm.patch(f"/api/admin/users/{me['id']}", json={"role": "advogado"}).status_code == 400
    assert cadm.patch(f"/api/admin/users/{me['id']}", json={"active": False}).status_code == 400
