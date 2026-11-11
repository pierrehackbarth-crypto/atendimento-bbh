from tests.conftest import login


def test_ficha_requires_login(env):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/ficha/db/fichas").status_code == 401
    assert c.get("/ficha/").status_code == 200  # a página abre; o adaptador manda para o login


def test_ficha_crud_shared_between_users(ca, cb, env):
    r = ca.put("/api/ficha/db/fichas/f1", json={"d": {"nome": "MARIA"}, "updatedAt": 1})
    assert r.status_code == 200
    r = cb.get("/api/ficha/db/fichas")
    assert [d["id"] for d in r.json()["docs"]] == ["f1"]  # todo o escritório vê as fichas
    etag = r.headers["etag"]
    assert cb.get("/api/ficha/db/fichas", headers={"If-None-Match": etag}).status_code == 304
    cb.put("/api/ficha/db/fichas/f1", json={"d": {"nome": "MARIA B"}, "updatedAt": 2})
    assert ca.get("/api/ficha/db/fichas", headers={"If-None-Match": etag}).status_code == 200
    assert ca.get("/api/ficha/db/fichas/f1").json()["data"]["d"]["nome"] == "MARIA B"


def test_csrf_and_readonly_collections(ca, env):
    tok = ca.headers.pop("X-CSRF-Token")
    assert ca.put("/api/ficha/db/fichas/f1", json={}).status_code == 403
    ca.headers["X-CSRF-Token"] = tok
    assert ca.put("/api/ficha/db/clientes/123", json={"l": []}).status_code == 403   # base só pelo admin/importação
    assert ca.get("/api/ficha/db/segredos").status_code == 404
    assert ca.put("/api/ficha/db/fichas/..", json={}).status_code in (400, 404)


def test_lixeira_delete_only_admin_unless_restored(ca, env):
    ca.put("/api/ficha/db/lixeira/f9", json={"d": {"nome": "X"}})
    assert ca.delete("/api/ficha/db/lixeira/f9").status_code == 403
    ca.put("/api/ficha/db/fichas/f9", json={"d": {"nome": "X"}})   # restauração: volta para fichas, depois sai da lixeira
    assert ca.delete("/api/ficha/db/lixeira/f9").status_code == 200


def test_assets_encrypted_and_authenticated(ca, env):
    import glob, os
    r = ca.post("/api/ficha/assets", files={"file": ("laudo.pdf", b"%PDF-1.4 conteudo secreto", "application/pdf")})
    a = r.json()
    assert ca.get(a["url"]).content == b"%PDF-1.4 conteudo secreto"
    files = [p for p in glob.glob(os.path.join(env["storage"], "*", "*"))]
    assert files and all(b"conteudo secreto" not in open(p, "rb").read() for p in files)
    ca.delete(a["url"])
    assert ca.get(a["url"]).status_code == 404


def test_ai_fake_and_profiles(ca, env):
    r = ca.post("/api/ficha/ai", data={"input": "Resuma em JSON", "json": "1"})
    assert r.status_code == 200 and r.json()["value"] == {}
    me = ca.get("/api/ficha/me").json()
    assert ca.post("/api/ficha/profiles", json={"ids": [me["id"]]}).json()[me["id"]]["name"] == "Advogado A"
