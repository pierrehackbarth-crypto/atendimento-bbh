import json, logging, threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, Header
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
import io, os

from .config import get_settings
from .db import Base, engine
from .models import User, Client, ClientAccess, Attendance, AudioSegment, Document, AIRun, Job, AuditEvent, now
from .security import (get_db, current_user, create_session, check_password, load_client, load_attendance,
                       check_sensitive, hash_password, COOKIE, _th, gravacao_user)
from .permissions import effective as effective_perms, has as has_perm
from .files import validate, DOC_TYPES, AUDIO_TYPES, TRANSCRIBABLE, safe_name
from . import storage, pipeline, worker
from .schemas import FICHA_SCHEMA, validate as validate_schema, segment_transcript
from .audit import audit
from .ficha_api import router as ficha_router
from .admin_api import router as admin_router


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
CONSENT_VERSION = "2026-10"
_stop = threading.Event()


@asynccontextmanager
async def lifespan(app):
    if get_settings().run_worker_in_process:
        threading.Thread(target=worker.loop, args=(_stop,), daemon=True).start()
    yield
    _stop.set()


app = FastAPI(title="THANOS – Atendimento (módulo vermelho) – Buss & Hackbarth", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "microphone=(self), camera=()"
    if request.url.path.startswith("/ficha"):
        # a ficha usa scripts embutidos, fontes do Google e a consulta pública de CEP
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline'; worker-src 'self' blob:; "
            "connect-src 'self' https://viacep.com.br https://brasilapi.com.br; frame-src 'self' blob:; frame-ancestors 'none'")
    else:
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                                                   "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------- autenticação ----------------
class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, response: Response, db=Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if not u or not u.active or not check_password(body.password, u.password_hash):
        raise HTTPException(401, "E-mail ou senha inválidos")
    csrf = create_session(db, u, response)
    return {"csrf": csrf, "user": {"id": u.id, "name": u.name, "role": u.role}}


@app.post("/api/logout")
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(get_db)):
    from .models import SessionToken
    tok = request.cookies.get(COOKIE)
    if tok:
        st = db.get(SessionToken, _th(tok))
        if st:
            db.delete(st)
            db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request, user=Depends(current_user)):
    s = get_settings()
    return {"user": {"id": user.id, "name": user.name, "role": user.role,
                     "can_view_sensitive": has_perm(user, "docs_sensiveis"), "perms": effective_perms(user)},
            "csrf": request.state.csrf,
            "limits": {"max_audio_upload_mb": s.max_audio_upload_mb, "max_recording_minutes": s.max_recording_minutes,
                       "max_attachment_mb": s.max_attachment_mb, "max_attachments": s.max_attachments_per_attendance,
                       "temp_audio_ttl_hours": s.temp_audio_ttl_hours},
            "consent_version": CONSENT_VERSION}


# ---------------- clientes ----------------
class ClientIn(BaseModel):
    name: str
    cpf: str | None = None


@app.get("/api/clients")
def list_clients(q: str = "", user=Depends(gravacao_user), db=Depends(get_db)):
    stmt = select(Client)
    if user.role != "admin":
        stmt = stmt.where((Client.owner_id == user.id) | Client.id.in_(select(ClientAccess.client_id).where(ClientAccess.user_id == user.id)))
    if q:
        stmt = stmt.where(Client.name.ilike(f"%{q}%") | (Client.cpf == q))
    return [{"id": c.id, "name": c.name, "cpf": c.cpf} for c in db.scalars(stmt.order_by(Client.name).limit(200))]


@app.post("/api/clients")
def create_client(body: ClientIn, user=Depends(gravacao_user), db=Depends(get_db)):
    c = Client(name=body.name.strip()[:200], cpf=(body.cpf or None), owner_id=user.id)
    db.add(c)
    audit(db, "client_created", user_id=user.id)
    db.commit()
    return {"id": c.id, "name": c.name, "cpf": c.cpf}


@app.post("/api/clients/{cid}/access")
def grant_access(cid: str, body: dict, user=Depends(gravacao_user), db=Depends(get_db)):
    c = load_client(db, user, cid)
    if not (user.role == "admin" or c.owner_id == user.id):
        raise HTTPException(403, "Somente o responsável pelo cliente pode conceder acesso")
    target = db.scalar(select(User).where(User.email == str(body.get("email", "")).lower()))
    if not target:
        raise HTTPException(404, "Usuário não encontrado")
    if not db.get(ClientAccess, (cid, target.id)):
        db.add(ClientAccess(client_id=cid, user_id=target.id))
    audit(db, "client_access_granted", user_id=user.id, target=target.id)
    db.commit()
    return {"ok": True}


# ---------------- atendimentos ----------------
def att_view(db, att: Attendance, user: User):
    segs = db.scalars(select(AudioSegment).where(AudioSegment.attendance_id == att.id).order_by(AudioSegment.seq)).all()
    docs = db.scalars(select(Document).where(Document.attendance_id == att.id, Document.status != "removed").order_by(Document.created_at)).all()
    runs = db.scalars(select(AIRun).where(AIRun.attendance_id == att.id, AIRun.kind == "summary").order_by(AIRun.created_at.desc())).all()
    jobs = db.scalars(select(Job).where(Job.attendance_id == att.id).order_by(Job.created_at)).all()
    latest = runs[0] if runs else None
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({att.created_by, att.responsible_id, att.finalized_by, att.consent_by} - {None})))}
    transcript = att.transcript_revised if att.transcript_revised is not None else att.transcript_original
    return {
        "id": att.id, "client_id": att.client_id, "status": att.status, "failed_step": att.failed_step, "last_error": att.last_error,
        "version": att.version, "created_at": att.created_at, "updated_at": att.updated_at,
        "created_by": names.get(att.created_by), "responsible": names.get(att.responsible_id),
        "consent": {"given": att.consent_given, "at": att.consent_at, "by": names.get(att.consent_by), "version": att.consent_text_version},
        "notes": att.notes, "recording_seconds": att.recording_seconds,
        "audio": {"status": att.audio_status, "deleted_at": att.audio_deleted_at, "result": att.audio_deletion_result,
                  "segments": [{"seq": s.seq, "size": s.size, "duration_s": s.duration_s, "status": s.status} for s in segs]},
        "transcript": {"original": att.transcript_original, "revised": att.transcript_revised, "model": att.transcript_model,
                       "completed_at": att.transcript_completed_at, "segments": segment_transcript(transcript or "")},
        "documents": [{"id": d.id, "name": d.original_name, "type": d.doc_type, "mime": d.mime, "size": d.size, "status": d.status,
                       "problem": d.problem, "pages": d.pages, "pages_visual": d.pages_visual, "sensitive": d.sensitive} for d in docs],
        "ai_latest": ({"id": latest.id, "model": latest.model, "created_at": latest.created_at, "ficha": latest.output_json["ficha"],
                       "calculos": latest.output_json.get("calculos"), "warnings": latest.warnings,
                       "is_base_of_revision": latest.id == att.ficha_revisada_base_run} if latest else None),
        "ai_runs": [{"id": r.id, "model": r.model, "created_at": r.created_at} for r in runs],
        "ficha_revisada": att.ficha_revisada, "ficha_final": att.ficha_final, "finalized_at": att.finalized_at,
        "finalized_by": names.get(att.finalized_by),
        "jobs": [{"kind": j.kind, "status": j.status, "attempts": j.attempts, "error": j.last_error} for j in jobs],
    }


@app.get("/api/clients/{cid}/attendances")
def list_attendances(cid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    load_client(db, user, cid)
    rows = db.scalars(select(Attendance).where(Attendance.client_id == cid).order_by(Attendance.created_at.desc())).all()
    return [{"id": a.id, "status": a.status, "created_at": a.created_at, "audio_status": a.audio_status} for a in rows]


@app.post("/api/clients/{cid}/attendances")
def create_attendance(cid: str, user=Depends(gravacao_user), db=Depends(get_db), idempotency_key: str | None = Header(None)):
    load_client(db, user, cid)
    if idempotency_key:
        ex = db.scalar(select(Attendance).where(Attendance.created_by == user.id, Attendance.idempotency_key == idempotency_key[:80]))
        if ex:
            return att_view(db, ex, user)
    a = Attendance(client_id=cid, created_by=user.id, responsible_id=user.id, idempotency_key=(idempotency_key or None) and idempotency_key[:80])
    db.add(a)
    db.flush()
    audit(db, "attendance_created", a.id, user.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        ex = db.scalar(select(Attendance).where(Attendance.created_by == user.id, Attendance.idempotency_key == idempotency_key[:80]))
        return att_view(db, ex, user)
    return att_view(db, a, user)


@app.get("/api/attendances/{aid}")
def get_attendance(aid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    return att_view(db, a, user)


class PatchIn(BaseModel):
    version: int
    notes: str | None = None
    consent: bool | None = None
    transcript_revised: str | None = None
    ficha_revisada: dict | None = None
    status: str | None = None  # somente "recording" <-> "draft" (feito pela interface)


def _editable(a):
    if a.status == "finalized":
        raise HTTPException(409, "Atendimento finalizado: não pode ser alterado")


@app.patch("/api/attendances/{aid}")
def patch_attendance(aid: str, body: PatchIn, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    if body.version != a.version:
        raise HTTPException(409, "O atendimento foi alterado por outra pessoa. Recarregue antes de salvar.")
    if body.notes is not None:
        a.notes = body.notes[:20000]
    if body.consent is not None:
        if body.consent and not a.consent_given:
            a.consent_given, a.consent_at, a.consent_by, a.consent_text_version = True, now(), user.id, CONSENT_VERSION
            audit(db, "consent_recorded", a.id, user.id, version=CONSENT_VERSION)
        elif not body.consent and a.consent_given:
            a.consent_given = False
            audit(db, "consent_revoked", a.id, user.id)
    if body.transcript_revised is not None:
        if a.transcript_original is None:
            raise HTTPException(409, "Ainda não há transcrição para revisar")
        a.transcript_revised = body.transcript_revised[:400000]
        audit(db, "transcript_revised", a.id, user.id)
    if body.ficha_revisada is not None:
        try:
            validate_schema(body.ficha_revisada, FICHA_SCHEMA)
        except Exception:
            raise HTTPException(422, "Ficha fora da estrutura esperada")
        a.ficha_revisada = body.ficha_revisada
        audit(db, "ficha_revised", a.id, user.id)
        pipeline.refresh_status(db, a)
    if body.status in ("recording", "draft") and a.status in ("draft", "recording", "awaiting_review", "failed"):
        if body.status == "recording" and not a.consent_given:
            raise HTTPException(409, "Registre a ciência e autorização do cliente antes de gravar")
        a.status = body.status
        if body.status == "draft":
            pipeline.refresh_status(db, a)
    a.version += 1
    db.commit()
    return att_view(db, a, user)


# ---------------- áudio ----------------
@app.post("/api/attendances/{aid}/audio")
async def upload_audio(aid: str, seq: int = Form(...), duration_s: float = Form(0), file: UploadFile = File(...),
                       user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    if not a.consent_given:
        raise HTTPException(409, "Registre a ciência e autorização do cliente antes de enviar áudio")
    if a.audio_status in ("deleted", "expired") and a.transcript_original:
        raise HTTPException(409, "O áudio deste atendimento já foi descartado")
    s = get_settings()
    data = await file.read(s.max_audio_upload_mb * 1024 * 1024 + 1)
    ext = validate(file.filename or "audio.webm", file.content_type or "", data, AUDIO_TYPES, s.max_audio_upload_mb * 1024 * 1024)
    if ext not in TRANSCRIBABLE:
        raise HTTPException(415, "Formato de áudio não aceito para transcrição")
    total = (db.scalar(select(func.sum(AudioSegment.duration_s)).where(AudioSegment.attendance_id == aid)) or 0) + max(0, duration_s)
    if total > s.max_recording_minutes * 60 + 30:
        raise HTTPException(413, f"Duração total acima de {s.max_recording_minutes} minutos")
    existing = db.scalar(select(AudioSegment).where(AudioSegment.attendance_id == aid, AudioSegment.seq == seq))
    sha = storage.sha256(data)
    if existing:  # reenvio do mesmo segmento (retentativa) não duplica
        if existing.sha256 == sha:
            return att_view(db, a, user)
        raise HTTPException(409, "Segmento já enviado com conteúdo diferente")
    prev = a.status
    a.status = "uploading"
    db.commit()
    key = storage.put(data, "a_")
    size = len(data)
    del data
    db.add(AudioSegment(attendance_id=aid, seq=seq, storage_key=key, mime=(file.content_type or "").split(";")[0], size=size,
                        duration_s=max(0, duration_s), sha256=sha))
    a.recording_seconds = total
    a.audio_status = "stored"
    a.status = "draft" if prev in ("recording", "uploading", "draft") else prev
    pipeline.refresh_status(db, a)
    a.version += 1
    audit(db, "audio_segment_uploaded", aid, user.id, seq=seq)
    db.commit()
    return att_view(db, a, user)


# ---------------- documentos ----------------
@app.post("/api/attendances/{aid}/documents")
async def upload_documents(aid: str, files: list[UploadFile] = File(...), user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    s = get_settings()
    count = db.scalar(select(func.count()).select_from(Document).where(Document.attendance_id == aid, Document.status != "removed")) or 0
    if count + len(files) > s.max_attachments_per_attendance:
        raise HTTPException(413, f"Limite de {s.max_attachments_per_attendance} anexos por atendimento")
    max_b = s.max_attachment_mb * 1024 * 1024
    staged = []
    for f in files:  # valida todos antes de gravar qualquer um
        data = await f.read(max_b + 1)
        ext = validate(f.filename or "", f.content_type or "", data, DOC_TYPES, max_b)
        staged.append((f, data, ext))
    for f, data, ext in staged:
        key = storage.put(data, "d_")
        d = Document(attendance_id=aid, original_name=safe_name(f.filename), storage_key=key, mime=f.content_type.split(";")[0],
                     ext="jpg" if ext == "jpeg" else ext, size=len(data), sha256=storage.sha256(data), created_by=user.id)
        db.add(d)
        db.flush()
        audit(db, "document_uploaded", aid, user.id, document_id=d.id, size=len(data))
    a.version += 1
    db.commit()
    return att_view(db, a, user)


@app.delete("/api/attendances/{aid}/documents/{did}")
def remove_document(aid: str, did: str, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    d = db.get(Document, did)
    if not d or d.attendance_id != aid or d.status == "removed":
        raise HTTPException(404, "Documento não encontrado")
    for k in (d.storage_key, d.text_key):
        if k:
            storage.delete(k)
    d.storage_key, d.text_key, d.status, d.removed_at = None, None, "removed", now()
    a.version += 1
    audit(db, "document_removed", aid, user.id, document_id=did)
    db.commit()
    return att_view(db, a, user)


@app.get("/api/attendances/{aid}/documents/{did}/file")
def download_document(aid: str, did: str, user=Depends(gravacao_user), db=Depends(get_db)):
    load_attendance(db, user, aid)
    d = db.get(Document, did)
    if not d or d.attendance_id != aid or not d.storage_key:
        raise HTTPException(404, "Documento não encontrado")
    check_sensitive(user, d)
    audit(db, "document_viewed", aid, user.id, document_id=did)
    db.commit()
    data = storage.get(d.storage_key)
    return Response(data, media_type=d.mime, headers={"Content-Disposition": f'inline; filename="documento.{d.ext}"',
                                                     "Cache-Control": "private, no-store"})


# ---------------- processamento ----------------
@app.post("/api/attendances/{aid}/transcribe")
def transcribe(aid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    segs = db.scalars(select(AudioSegment).where(AudioSegment.attendance_id == aid)).all()
    if not segs:
        raise HTTPException(409, "Não há gravação para transcrever")
    pend = [s for s in segs if s.status != "transcribed"]
    if any(s.status in ("deleted", "expired") for s in pend):
        raise HTTPException(409, "Parte do áudio já foi excluída (prazo de retenção). Não é possível retranscrever.")
    for s in pend:
        pipeline.enqueue(db, aid, "transcribe_segment", target_id=s.id, user_id=user.id)
    pipeline._maybe_compose_transcript(db, a)
    pipeline.refresh_status(db, a)
    a.version += 1
    db.commit()
    return att_view(db, a, user)


@app.post("/api/attendances/{aid}/analyze-documents")
def analyze_documents(aid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    docs = db.scalars(select(Document).where(Document.attendance_id == aid, Document.status.in_(["uploaded", "failed"]))).all()
    for d in docs:
        if d.status == "failed" and d.problem and ("senha" in d.problem or "corromp" in d.problem):
            continue  # não adianta reprocessar arquivo protegido/corrompido
        pipeline.enqueue(db, aid, "extract_document", target_id=d.id, user_id=user.id)
    pipeline.refresh_status(db, a)
    a.version += 1
    db.commit()
    return att_view(db, a, user)


@app.post("/api/attendances/{aid}/generate")
def generate(aid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    transcript = a.transcript_revised if a.transcript_revised is not None else a.transcript_original
    n_runs = db.scalar(select(func.count()).select_from(AIRun).where(AIRun.attendance_id == aid, AIRun.kind == "summary")) or 0
    # cada solicitação explícita gera uma nova versão; cliques repetidos enquanto há uma na fila não duplicam
    active = db.scalar(select(Job).where(Job.attendance_id == aid, Job.kind == "summarize", Job.status.in_(["queued", "running"])))
    if not active:
        if not (transcript or a.notes.strip() or db.scalar(select(func.count()).select_from(Document).where(Document.attendance_id == aid, Document.status.in_(["extracted", "partial"])))):
            raise HTTPException(409, "Transcreva a gravação, analise documentos ou escreva anotações antes de gerar a ficha")
        pipeline.enqueue(db, aid, "summarize", dedupe=f"summarize:{aid}:{n_runs + 1}", user_id=user.id, max_attempts=3)
    pipeline.refresh_status(db, a)
    a.version += 1
    db.commit()
    return att_view(db, a, user)


@app.post("/api/attendances/{aid}/retry")
def retry(aid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    _editable(a)
    for j in db.scalars(select(Job).where(Job.attendance_id == aid, Job.status == "failed")).all():
        j.status, j.attempts, j.next_run_at, j.last_error = "queued", 0, now(), None
    pipeline.refresh_status(db, a)
    a.version += 1
    db.commit()
    return att_view(db, a, user)


class FinalizeIn(BaseModel):
    version: int
    ficha_final: dict
    confirm_audio_deletion: bool = False


@app.post("/api/attendances/{aid}/finalize")
def finalize(aid: str, body: FinalizeIn, user=Depends(gravacao_user), db=Depends(get_db)):
    a = load_attendance(db, user, aid)
    if a.status == "finalized":
        return att_view(db, a, user)  # idempotente
    if body.version != a.version:
        raise HTTPException(409, "O atendimento foi alterado por outra pessoa. Recarregue antes de finalizar.")
    try:
        validate_schema(body.ficha_final, FICHA_SCHEMA)
    except Exception:
        raise HTTPException(422, "Ficha fora da estrutura esperada")
    has_audio = db.scalar(select(func.count()).select_from(AudioSegment).where(AudioSegment.attendance_id == aid, AudioSegment.storage_key.is_not(None))) > 0
    if has_audio and not pipeline.transcription_complete(db, a):
        raise HTTPException(409, "Há gravação ainda não transcrita. Transcreva antes de finalizar.")
    if has_audio and not body.confirm_audio_deletion:
        raise HTTPException(409, "Confirme a ciência de que o áudio será excluído definitivamente")
    # 1) persiste transcrição e ficha final
    a.ficha_final = body.ficha_final
    a.ficha_revisada = body.ficha_final
    a.status, a.finalized_at, a.finalized_by = "finalized", now(), user.id
    a.version += 1
    audit(db, "attendance_finalized", aid, user.id)
    db.commit()
    db.refresh(a)
    # 2) confirma a persistência antes de excluir o áudio
    if a.ficha_final != body.ficha_final or (has_audio and not a.transcript_original):
        raise HTTPException(500, "Não foi possível confirmar a gravação da ficha; o áudio foi mantido")
    # 3) regra: transcrição concluída + ficha finalizada = exclusão do áudio
    if has_audio or a.audio_status == "audio_deletion_pending":
        pipeline.delete_audio(db, a, reason="finalized")
        db.commit()
    return att_view(db, a, user)


@app.get("/api/attendances/{aid}/audit")
def audit_trail(aid: str, user=Depends(gravacao_user), db=Depends(get_db)):
    load_attendance(db, user, aid)
    ev = db.scalars(select(AuditEvent).where(AuditEvent.attendance_id == aid).order_by(AuditEvent.at)).all()
    return [{"action": e.action, "at": e.at, "meta": e.meta} for e in ev]


# ---------------- frontend ----------------
STATIC = os.path.join(os.path.dirname(__file__), "static")
FICHA_DIR = os.path.join(STATIC, "ficha")
app.include_router(ficha_router)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


VENDOR = {
    "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js": "/ficha/vendor/jszip.min.js",
    "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js": "/ficha/vendor/pdf.min.js",
    "https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js": "/ficha/vendor/pdf.worker.min.js",
    "https://cdn.jsdelivr.net/npm/pdfmake@0.2.10/build/pdfmake.min.js": "/ficha/vendor/pdfmake.min.js",
    "https://cdn.jsdelivr.net/npm/pdfmake@0.2.10/build/vfs_fonts.js": "/ficha/vendor/vfs_fonts.js",
    "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js": "/ficha/vendor/xlsx.full.min.js",
}


@app.get("/ficha")
def ficha_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ficha/", status_code=307)


@app.get("/ficha/")
def ficha_page():
    """A ficha de atendimento, com o adaptador que liga os recursos dela a este servidor."""
    html = open(os.path.join(FICHA_DIR, "index.html"), encoding="utf-8").read()
    shim = '<script src="/static/ficha-shim.js"></script>'
    i = html.find("<meta charset")
    j = html.find(">", i) + 1 if i >= 0 else 0
    html = html[:j] + shim + html[j:]
    # bibliotecas servidas pelo próprio servidor, sem depender de CDN
    for url, local in VENDOR.items():
        html = html.replace(url, local)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


app.mount("/ficha/vendor", StaticFiles(directory=os.path.join(FICHA_DIR, "vendor")), name="ficha_vendor")
if os.path.isdir(os.path.join(FICHA_DIR, "cep")):
    app.mount("/ficha/cep", StaticFiles(directory=os.path.join(FICHA_DIR, "cep")), name="ficha_cep")


@app.get("/usuarios")
def usuarios_page():
    return FileResponse(os.path.join(STATIC, "usuarios.html"), headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    """THANOS: tela de entrada e painel de módulos (cada joia é um módulo)."""
    return FileResponse(os.path.join(STATIC, "thanos", "index.html"), headers={"Cache-Control": "no-store"})


@app.get("/atendimento")
def atendimento_page():
    """Módulo vermelho (Atendimento): gravação e transcrição com IA."""
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-store"})
