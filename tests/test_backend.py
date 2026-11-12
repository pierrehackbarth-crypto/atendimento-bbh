import os, glob
from sqlalchemy import select
from tests.conftest import make_pdf, WEBM


def new_att(ca, env, key="k1"):
    r = ca.post(f"/api/clients/{env['client']}/attendances", headers={"Idempotency-Key": key})
    assert r.status_code == 200, r.text
    return r.json()


def drain():
    from app import worker
    return worker.drain()


def stored_files(env):
    return [p for p in glob.glob(os.path.join(env["storage"], "*", "*")) if not p.endswith(".tmp")]


def test_idempotent_creation(ca, env):
    a1 = new_att(ca, env, "same"); a2 = new_att(ca, env, "same")
    assert a1["id"] == a2["id"]


def test_access_denied_other_user(ca, cb, env):
    a = new_att(ca, env)
    assert cb.get(f"/api/attendances/{a['id']}").status_code == 404
    assert cb.post(f"/api/attendances/{a['id']}/transcribe").status_code == 404
    assert cb.get(f"/api/clients/{env['client']}/attendances").status_code == 404
    # após concessão de acesso, B passa a ver
    assert ca.post(f"/api/clients/{env['client']}/access", json={"email": "b@x.com"}).status_code == 200
    assert cb.get(f"/api/attendances/{a['id']}").status_code == 200


def test_csrf_required(ca, env):
    a = new_att(ca, env)
    tok = ca.headers.pop("X-CSRF-Token")
    assert ca.patch(f"/api/attendances/{a['id']}", json={"version": a["version"], "notes": "x"}).status_code == 403
    ca.headers["X-CSRF-Token"] = tok


def test_audio_requires_consent_and_validation(ca, env):
    a = new_att(ca, env)
    up = lambda data, name="seg.webm", mime="audio/webm", seq=0: ca.post(f"/api/attendances/{a['id']}/audio", data={"seq": seq, "duration_s": 10}, files={"file": (name, data, mime)})
    assert up(WEBM).status_code == 409  # sem consentimento
    a = ca.patch(f"/api/attendances/{a['id']}", json={"version": a["version"], "consent": True}).json()
    assert a["consent"]["given"] and a["consent"]["by"] == "Advogado A"
    assert up(b"RIFF....fake", "x.webm").status_code == 415  # assinatura errada
    assert up(WEBM, "x.exe", "application/octet-stream").status_code == 415
    assert up(WEBM).status_code == 200
    assert up(WEBM).status_code == 200  # reenvio idêntico (retentativa) não duplica
    assert up(WEBM + b"x").status_code == 409


def test_documents_validation_and_limits(ca, env):
    a = new_att(ca, env)
    aid = a["id"]
    r = ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("x.pdf", b"not a pdf", "application/pdf"))])
    assert r.status_code == 415
    r = ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("x.png", make_pdf(), "image/png"))])
    assert r.status_code == 415
    big = b"%PDF-" + b"0" * (1024 * 1024 + 10)
    assert ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("g.pdf", big, "application/pdf"))]).status_code == 413
    four = [("files", (f"d{i}.pdf", make_pdf(), "application/pdf")) for i in range(4)]
    assert ca.post(f"/api/attendances/{aid}/documents", files=four).status_code == 413
    assert ca.post(f"/api/attendances/{aid}/documents", files=four[:2]).status_code == 200


def test_pdf_text_scanned_password_corrupt(ca, env):
    a = new_att(ca, env); aid = a["id"]
    files = [("files", ("cnis.pdf", make_pdf(), "application/pdf")),
             ("files", ("laudo_digitalizado.pdf", make_pdf(text_pages=(), scanned_pages=2), "application/pdf")),
             ("files", ("protegido.pdf", make_pdf(password="123"), "application/pdf"))]
    ca.post(f"/api/attendances/{aid}/documents", files=files)
    ca.post(f"/api/attendances/{aid}/analyze-documents"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    st = {d["name"]: d for d in v["documents"]}
    assert st["cnis.pdf"]["status"] == "extracted" and st["cnis.pdf"]["pages"] == 1
    assert st["laudo_digitalizado.pdf"]["pages_visual"] == 2 and st["laudo_digitalizado.pdf"]["status"] == "partial"
    assert st["protegido.pdf"]["status"] == "failed" and "senha" in st["protegido.pdf"]["problem"]
    # corrompido (novo atendimento: limite de 3 anexos no teste)
    aid = new_att(ca, env, "k2")["id"]
    assert ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("ruim.pdf", b"%PDF-1.4 lixo", "application/pdf"))]).status_code == 200
    ca.post(f"/api/attendances/{aid}/analyze-documents"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    ruim = [d for d in v["documents"] if d["name"] == "ruim.pdf"][0]
    assert ruim["status"] == "failed"


def test_full_flow_references_review_and_audio_deletion(ca, env):
    a = new_att(ca, env); aid = a["id"]
    a = ca.patch(f"/api/attendances/{aid}", json={"version": a["version"], "consent": True}).json()
    for i in range(2):
        assert ca.post(f"/api/attendances/{aid}/audio", data={"seq": i, "duration_s": 60}, files={"file": (f"s{i}.webm", WEBM + bytes([i]), "audio/webm")}).status_code == 200
    ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("cnis.pdf", make_pdf(), "application/pdf"))])
    ca.post(f"/api/attendances/{aid}/transcribe")
    ca.post(f"/api/attendances/{aid}/transcribe")  # idempotente
    from app.db import SessionLocal
    from app.models import Job
    s = SessionLocal(); assert len(s.scalars(select(Job).where(Job.kind == "transcribe_segment")).all()) == 2; s.close()
    ca.post(f"/api/attendances/{aid}/analyze-documents"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["transcript"]["original"] and v["transcript"]["segments"][0][0] == "T001"
    ca.post(f"/api/attendances/{aid}/generate"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["status"] == "awaiting_review"
    f = v["ai_latest"]["ficha"]
    assert f["divergencias"] and {x["tipo"] for x in f["divergencias"][0]["fontes"]} == {"transcricao", "documento"}
    assert v["ai_latest"]["calculos"]["cnis"]["total_dias"] > 0
    # edição manual não é sobrescrita ao reprocessar
    rev = v["ficha_revisada"]; rev["motivo_consulta"] = "EDITADO PELO ADVOGADO"
    v = ca.patch(f"/api/attendances/{aid}", json={"version": v["version"], "ficha_revisada": rev}).json()
    ca.post(f"/api/attendances/{aid}/generate"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert len(v["ai_runs"]) == 2 and v["ficha_revisada"]["motivo_consulta"] == "EDITADO PELO ADVOGADO"
    # transcrição revisada preservada separada da original
    v = ca.patch(f"/api/attendances/{aid}", json={"version": v["version"], "transcript_revised": "texto revisado"}).json()
    assert v["transcript"]["original"] != v["transcript"]["revised"]
    n_before = len(stored_files(env))
    # finalização exige confirmação
    assert ca.post(f"/api/attendances/{aid}/finalize", json={"version": v["version"], "ficha_final": v["ficha_revisada"]}).status_code == 409
    r = ca.post(f"/api/attendances/{aid}/finalize", json={"version": v["version"], "ficha_final": v["ficha_revisada"], "confirm_audio_deletion": True})
    v = r.json()
    assert v["status"] == "finalized" and v["audio"]["status"] == "deleted" and v["audio"]["deleted_at"]
    assert all(s["status"] == "transcribed" for s in v["audio"]["segments"])
    assert len(stored_files(env)) == n_before - 2   # só os 2 segmentos de áudio saíram; documento e texto ficaram
    assert v["transcript"]["original"] and v["ficha_final"]["motivo_consulta"] == "EDITADO PELO ADVOGADO"
    # idempotente e bloqueado para edição
    assert ca.post(f"/api/attendances/{aid}/finalize", json={"version": 0, "ficha_final": v["ficha_final"]}).status_code == 200
    assert ca.patch(f"/api/attendances/{aid}", json={"version": v["version"], "notes": "x"}).status_code == 409
    acts = [e["action"] for e in ca.get(f"/api/attendances/{aid}/audit").json()]
    assert "audio_deleted" in acts and "attendance_finalized" in acts


def test_audio_deletion_retry(ca, env, monkeypatch):
    a = new_att(ca, env); aid = a["id"]
    a = ca.patch(f"/api/attendances/{aid}", json={"version": a["version"], "consent": True}).json()
    ca.post(f"/api/attendances/{aid}/audio", data={"seq": 0, "duration_s": 5}, files={"file": ("s.webm", WEBM, "audio/webm")})
    ca.post(f"/api/attendances/{aid}/transcribe"); drain()
    ca.post(f"/api/attendances/{aid}/generate"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    from app import storage
    real = storage.delete
    monkeypatch.setattr(storage, "delete", lambda k: False)
    v = ca.post(f"/api/attendances/{aid}/finalize", json={"version": v["version"], "ficha_final": v["ficha_revisada"], "confirm_audio_deletion": True}).json()
    assert v["status"] == "finalized" and v["audio"]["status"] == "audio_deletion_pending"
    monkeypatch.setattr(storage, "delete", real)
    from app.db import SessionLocal
    from app.models import Job
    from app.models import now
    s = SessionLocal()
    for j in s.scalars(select(Job).where(Job.kind == "delete_audio")).all():
        j.next_run_at = now()
    s.commit(); s.close()
    drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["audio"]["status"] == "deleted"


def test_documents_only_ficha(ca, env):
    a = new_att(ca, env); aid = a["id"]
    assert ca.post(f"/api/attendances/{aid}/generate").status_code == 409
    a = ca.patch(f"/api/attendances/{aid}", json={"version": a["version"], "notes": "Cliente quer revisar benefício."}).json()
    ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("cnis.pdf", make_pdf(), "application/pdf"))])
    ca.post(f"/api/attendances/{aid}/analyze-documents"); drain()
    ca.post(f"/api/attendances/{aid}/generate"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["status"] == "awaiting_review" and v["ai_latest"]["ficha"]["documentos_analisados"]
    v = ca.post(f"/api/attendances/{aid}/finalize", json={"version": v["version"], "ficha_final": v["ficha_revisada"]}).json()
    assert v["status"] == "finalized" and v["audio"]["status"] == "none"


def test_summary_failure_preserves_previous_steps(ca, env, monkeypatch):
    a = new_att(ca, env); aid = a["id"]
    a = ca.patch(f"/api/attendances/{aid}", json={"version": a["version"], "consent": True}).json()
    ca.post(f"/api/attendances/{aid}/audio", data={"seq": 0, "duration_s": 5}, files={"file": ("s.webm", WEBM, "audio/webm")})
    ca.post(f"/api/attendances/{aid}/transcribe"); drain()
    from app import ai
    def boom(*a, **k): raise ai.AIError("falha simulada", retryable=False)
    monkeypatch.setattr(ai, "summarize", boom)
    ca.post(f"/api/attendances/{aid}/generate"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["status"] == "failed" and v["failed_step"] == "summarize" and v["transcript"]["original"]
    monkeypatch.undo()


def test_ttl_sweep(ca, env, monkeypatch):
    a = new_att(ca, env); aid = a["id"]
    a = ca.patch(f"/api/attendances/{aid}", json={"version": a["version"], "consent": True}).json()
    ca.post(f"/api/attendances/{aid}/audio", data={"seq": 0, "duration_s": 5}, files={"file": ("s.webm", WEBM, "audio/webm")})
    from app.db import SessionLocal
    from app.models import AudioSegment
    from datetime import datetime, timedelta, timezone
    s = SessionLocal()
    seg = s.scalars(select(AudioSegment)).first(); seg.created_at = datetime.now(timezone.utc) - timedelta(hours=100); s.commit(); s.close()
    from app import worker
    worker.sweep()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["audio"]["status"] == "expired"
    assert ca.post(f"/api/attendances/{aid}/transcribe").status_code == 409


def test_sensitive_document_permission(ca, cb, env):
    a = new_att(ca, env); aid = a["id"]
    v = ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("laudo.pdf", make_pdf(), "application/pdf"))]).json()
    did = v["documents"][0]["id"]
    assert ca.get(f"/api/attendances/{aid}/documents/{did}/file").status_code == 200
    ca.post(f"/api/clients/{env['client']}/access", json={"email": "b@x.com"})
    from app.db import SessionLocal
    from app.models import User
    s = SessionLocal(); u = s.get(User, env["b"]); u.can_view_sensitive = False; s.commit(); s.close()
    assert cb.get(f"/api/attendances/{aid}/documents/{did}/file").status_code == 403


def test_document_not_stuck_when_ai_fails(ca, env, monkeypatch):
    from app import ai
    aid = new_att(ca, env)["id"]
    ca.post(f"/api/attendances/{aid}/documents", files=[("files", ("cnis.pdf", make_pdf(["CNIS vinculo empresa X 01/01/1995 a 01/01/2000"]), "application/pdf"))])
    def boom(*a, **k): raise ai.AIError("BadRequestError (400)", retryable=False)
    monkeypatch.setattr(ai, "extract_document", boom)
    ca.post(f"/api/attendances/{aid}/analyze-documents"); drain()
    v = ca.get(f"/api/attendances/{aid}").json()
    assert v["documents"][0]["status"] == "failed"


def test_thanos_entrada_e_modulo_vermelho(env):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and "THANOS" in r.text and "/static/thanos/thanos.js" in r.text
    r = c.get("/atendimento")
    assert r.status_code == 200 and "/static/app.js" in r.text
    assert c.get("/static/thanos/thanos.js").status_code == 200
    assert c.get("/static/thanos/thanos.css").status_code == 200
