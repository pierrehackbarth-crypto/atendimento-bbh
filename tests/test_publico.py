"""Proteções para o acesso pela internet."""
from fastapi.testclient import TestClient


def _cli():
    from app.main import app
    return TestClient(app)


def test_login_lockout_per_email(env):
    c = _cli()
    for _ in range(5):
        assert c.post("/api/login", json={"email": "a@x.com", "password": "errada-123456"}).status_code == 401
    r = c.post("/api/login", json={"email": "a@x.com", "password": "senha-segura-1"})
    assert r.status_code == 429 and "minuto" in r.json()["detail"]
    # outro usuário continua entrando
    assert c.post("/api/login", json={"email": "b@x.com", "password": "senha-segura-2"}).status_code == 200


def test_no_ip_lockout_behind_proxy(env):
    # atrás do Funnel todos chegam pelo mesmo endereço: erros de um não podem trancar os outros
    c = _cli()
    for i in range(30):
        c.post("/api/login", json={"email": f"x{i}@x.com", "password": "errada-123456"})
    assert c.post("/api/login", json={"email": "b@x.com", "password": "senha-segura-2"}).status_code == 200


def test_success_resets_counter(env):
    c = _cli()
    for _ in range(4):
        c.post("/api/login", json={"email": "a@x.com", "password": "errada-123456"})
    assert c.post("/api/login", json={"email": "a@x.com", "password": "senha-segura-1"}).status_code == 200
    for _ in range(4):
        c.post("/api/login", json={"email": "a@x.com", "password": "errada-123456"})
    assert c.post("/api/login", json={"email": "a@x.com", "password": "senha-segura-1"}).status_code == 200


def test_nothing_sensitive_without_login(env):
    c = _cli()
    assert c.get("/static/ficha/index.html").status_code == 404
    r = c.get("/ficha/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?next=")
    assert c.get("/openapi.json").status_code == 404
    for path in ("/api/ficha/db/fichas", "/api/ficha/db/clientes", "/api/ficha/db/nomes/a", "/api/admin/users", "/api/clients", "/api/me"):
        assert c.get(path).status_code == 401, path


def test_password_policy():
    from app.protecao import problema_senha
    assert problema_senha("curta1")
    assert problema_senha("somenteletras")
    assert problema_senha("1234567890")
    assert problema_senha("pierre2026xyz", "pierre@x.com")
    assert problema_senha("Atendimento-2026") is None
