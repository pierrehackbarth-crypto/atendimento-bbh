import uuid
from datetime import datetime, timezone
from sqlalchemy import (String, Integer, Boolean, DateTime, Text, ForeignKey, JSON,
                        UniqueConstraint, Index, Float)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return uuid.uuid4().hex


# Estados do atendimento (exigidos pela especificação)
ATT_STATES = ["draft", "recording", "uploading", "transcribing", "analyzing_documents",
              "generating_summary", "awaiting_review", "finalized", "failed"]
# Estado do áudio, controlado separadamente
AUDIO_STATES = ["none", "stored", "audio_deletion_pending", "deleted", "expired"]


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="advogado")  # admin | advogado | assistente
    can_view_sensitive: Mapped[bool] = mapped_column(Boolean, default=True)  # documentos médicos
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # permissões ajustadas pelo administrador; vazio = padrão do papel (ver app/permissions.py)
    perms: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SessionToken(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Client(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    cpf: Mapped[str | None] = mapped_column(String(14), nullable=True, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientAccess(Base):
    __tablename__ = "client_access"
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class Attendance(Base):
    __tablename__ = "attendances"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    responsible_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    failed_step: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    consent_text_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    notes: Mapped[str] = mapped_column(Text, default="")
    recording_seconds: Mapped[float] = mapped_column(Float, default=0)

    audio_status: Mapped[str] = mapped_column(String(30), default="none")
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_deletion_result: Mapped[str | None] = mapped_column(String(200), nullable=True)
    audio_deletion_attempts: Mapped[int] = mapped_column(Integer, default=0)

    transcript_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_revised: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    transcript_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ficha_revisada: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # edição do advogado (nunca sobrescrita pela IA)
    ficha_revisada_base_run: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ficha_final: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (UniqueConstraint("created_by", "idempotency_key", name="uq_att_idem"),)


class AudioSegment(Base):
    __tablename__ = "audio_segments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendances.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    mime: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[float] = mapped_column(Float, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="stored")  # stored | transcribed | failed | deleted | expired
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("attendance_id", "seq", name="uq_seg_seq"),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendances.id", ondelete="CASCADE"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(80), nullable=True)  # anexo definitivo (criptografado)
    text_key: Mapped[str | None] = mapped_column(String(80), nullable=True)     # texto extraído por página (criptografado)
    mime: Mapped[str] = mapped_column(String(60))
    ext: Mapped[str] = mapped_column(String(10))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    doc_type: Mapped[str] = mapped_column(String(40), default="outro")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded | extracting | extracted | partial | failed | removed
    problem: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_text: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages_visual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendances.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # transcription | doc_extraction | summary
    model: Mapped[str] = mapped_column(String(80))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProviderFile(Base):
    __tablename__ = "provider_files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendances.id", ondelete="CASCADE"), index=True)
    provider_file_id: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(20))  # document | audio
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | deleted | failed


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendances.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # transcribe_segment | extract_document | summarize | delete_audio | delete_provider_file
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (Index("ix_jobs_status_next", "status", "next_run_at"),)


class AuditEvent(Base):
    """Trilha de auditoria. Nunca guarda conteúdo de transcrição, documento ou áudio."""
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    attendance_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StoreDoc(Base):
    """Documentos da ficha de atendimento (fichas, lixeira, base de clientes), no mesmo formato que a ficha já usa."""
    __tablename__ = "store_docs"
    collection: Mapped[str] = mapped_column(String(40), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class StoreVersion(Base):
    """Contador por coleção: muda a cada gravação/exclusão, para a ficha saber quando recarregar."""
    __tablename__ = "store_versions"
    collection: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)


class Asset(Base):
    """Anexos da ficha (guardados criptografados no disco)."""
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    storage_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
