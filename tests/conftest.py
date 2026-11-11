import os, io, pytest
from cryptography.fernet import Fernet


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "st"))
    monkeypatch.setenv("STORAGE_AUDIO_DIR", str(tmp_path / "st"))
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("OPENAI_FAKE", "true")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("RUN_WORKER_IN_PROCESS", "false")
    monkeypatch.setenv("MAX_ATTACHMENTS_PER_ATTENDANCE", "3")
    monkeypatch.setenv("MAX_ATTACHMENT_MB", "1")
    from app.config import get_settings
    get_settings.cache_clear()
    from app import db as dbm, storage
    dbm.reset_engine(); storage.reset()
    from app.db import Base, engine, SessionLocal
    from app import models
    Base.metadata.create_all(engine())
    from app.security import hash_password
    s = SessionLocal()
    a = models.User(email="a@x.com", name="Advogado A", password_hash=hash_password("senha-segura-1"), role="advogado")
    b = models.User(email="b@x.com", name="Advogado B", password_hash=hash_password("senha-segura-2"), role="advogado")
    s.add_all([a, b]); s.commit()
    c = models.Client(name="Cliente de A", owner_id=a.id); s.add(c); s.commit()
    ids = {"a": a.id, "b": b.id, "client": c.id, "storage": str(tmp_path / "st")}
    s.close()
    yield ids
    dbm.reset_engine(); get_settings.cache_clear()


def login(client, email, pw):
    r = client.post("/api/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    return client


@pytest.fixture()
def ca(env):
    from fastapi.testclient import TestClient
    from app.main import app
    return login(TestClient(app), "a@x.com", "senha-segura-1")


@pytest.fixture()
def cb(env):
    from fastapi.testclient import TestClient
    from app.main import app
    return login(TestClient(app), "b@x.com", "senha-segura-2")


def make_pdf(text_pages=("CNIS – Extrato Previdenciário\nCERÂMICA BEIRA RIO LTDA 01/03/1996 15/07/2005",), scanned_pages=0, password=None):
    import pymupdf
    d = pymupdf.open()
    for t in text_pages:
        p = d.new_page(); p.insert_text((50, 72), t, fontsize=11)
    for _ in range(scanned_pages):
        p = d.new_page(); p.draw_rect(pymupdf.Rect(50, 50, 300, 300), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    kw = {}
    if password:
        kw = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password}
    b = d.tobytes(**kw); d.close(); return b


WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 2000
