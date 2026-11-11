"""Etapas de processamento (executadas pelo worker) e regra de descarte do áudio."""
import json, logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from . import storage, ai
from .config import get_settings
from .models import Attendance, AudioSegment, Document, AIRun, ProviderFile, Job, now
from .files import extract_pdf, check_image, guess_doc_type
from .schemas import segment_transcript, check_references, cnis_calculation, empty_ficha
from .audit import audit

log = logging.getLogger("atendimento")


class StepError(Exception):
    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = retryable


# ---------------- fila ----------------
def enqueue(db, att_id, kind, target_id=None, dedupe=None, user_id=None, max_attempts=4):
    """Idempotente: a mesma dedupe_key nunca gera dois jobs; job concluído não é repetido."""
    key = dedupe or f"{kind}:{att_id}:{target_id or ''}"
    j = db.scalar(select(Job).where(Job.dedupe_key == key))
    if j:
        if j.status == "failed":  # retentativa manual: reabre o mesmo job
            j.status, j.attempts, j.next_run_at, j.last_error = "queued", 0, now(), None
        return j
    j = Job(attendance_id=att_id, kind=kind, target_id=target_id, dedupe_key=key, requested_by=user_id, max_attempts=max_attempts)
    db.add(j)
    db.flush()
    return j


def ai_quota_ok(db, user_id) -> bool:
    if not user_id:
        return True
    since = datetime.now(timezone.utc) - timedelta(days=1)
    n = db.scalar(select(func.count()).select_from(AIRun).where(AIRun.created_by == user_id, AIRun.created_at >= since)) or 0
    return n < get_settings().max_ai_calls_per_user_per_day


# ---------------- transcrição ----------------
def run_transcribe_segment(db, job):
    seg = db.get(AudioSegment, job.target_id)
    if not seg or seg.status == "transcribed":
        return
    if seg.status in ("deleted", "expired") or not seg.storage_key:
        raise StepError("Áudio não está mais disponível (excluído ou expirado)", retryable=False)
    if not ai_quota_ok(db, job.requested_by):
        raise StepError("Limite diário de uso de IA atingido", retryable=False)
    audio = storage.get(seg.storage_key)  # em memória; nenhuma cópia temporária em disco
    ext = {"audio/webm": "webm", "video/webm": "webm", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav", "audio/x-wav": "wav"}.get(seg.mime, "webm")
    try:
        text, model = ai.transcribe(audio, f"segmento_{seg.seq:03d}.{ext}")
    except ai.AIError as e:
        raise StepError(str(e), e.retryable)
    finally:
        del audio
    seg.transcript_text, seg.status, seg.transcribed_at = text, "transcribed", now()
    db.add(AIRun(attendance_id=seg.attendance_id, kind="transcription", model=model, input_fingerprint=seg.sha256,
                 output_json={"segment": seg.seq, "chars": len(text)}, created_by=job.requested_by))
    att = db.get(Attendance, seg.attendance_id)
    att.transcript_model = model
    _maybe_compose_transcript(db, att)


def _maybe_compose_transcript(db, att):
    segs = db.scalars(select(AudioSegment).where(AudioSegment.attendance_id == att.id).order_by(AudioSegment.seq)).all()
    if segs and all(s.status == "transcribed" for s in segs):
        original = "\n\n".join((s.transcript_text or "").strip() for s in segs)
        if att.transcript_original != original:
            att.transcript_original = original
            if att.transcript_revised is None:
                att.transcript_revised = original   # ponto de partida da revisão; edições manuais nunca são sobrescritas
        att.transcript_completed_at = now()
        audit(db, "transcription_completed", att.id, segments=len(segs))


def transcription_complete(db, att) -> bool:
    segs = db.scalars(select(AudioSegment).where(AudioSegment.attendance_id == att.id)).all()
    return bool(segs) and all(s.status == "transcribed" for s in segs) and bool(att.transcript_original)


# ---------------- documentos ----------------
def run_extract_document(db, job):
    doc = db.get(Document, job.target_id)
    if not doc or doc.status in ("extracted", "partial", "removed") and _has_extraction(db, doc):
        return
    if doc.status == "removed":
        return
    if not ai_quota_ok(db, job.requested_by):
        raise StepError("Limite diário de uso de IA atingido", retryable=False)
    data = storage.get(doc.storage_key)
    doc.status = "extracting"
    db.commit()
    if doc.ext == "pdf":
        r = extract_pdf(data)
    else:
        r = check_image(data)
        r["page_images"] = {1: data}
    if r["status"] == "failed":
        doc.status, doc.problem = "failed", r["problem"]
        audit(db, "document_failed", doc.attendance_id, document_id=doc.id, reason=r["problem"])
        return
    pages = r["pages"]
    doc.pages = r.get("page_count")
    doc.pages_text = sum(1 for p in pages if p.get("text"))
    doc.pages_visual = sum(1 for p in pages if p.get("needs_visual"))
    text_all = "\n".join(p.get("text", "") for p in pages)
    if doc.doc_type == "outro":
        doc.doc_type = guess_doc_type(doc.original_name, text_all)
    doc.text_key = storage.put(json.dumps(pages, ensure_ascii=False).encode(), "t_")
    # PDF com páginas digitalizadas: envia o PDF ao modelo (texto + imagem de cada página);
    # PDF totalmente textual: envia apenas o texto por página.
    pdf_bytes = data if (doc.ext == "pdf" and doc.pages_visual) else None
    images = {} if doc.ext == "pdf" else r.get("page_images", {})
    pf_id = None
    try:
        if pdf_bytes is not None and get_settings().openai_use_files_api and not get_settings().openai_fake:
            pf_id = ai.upload_provider_file(f"{doc.id}.pdf", pdf_bytes)
            db.add(ProviderFile(attendance_id=doc.attendance_id, provider_file_id=pf_id, purpose="user_data", kind="document"))
            db.commit()
        out, model = ai.extract_document(doc.id, doc.original_name, pages, images, None if pf_id else pdf_bytes, use_file_id=pf_id)
    except ai.AIError as e:
        doc.status = "uploaded"
        raise StepError(str(e), e.retryable)
    finally:
        del data
        if pf_id:
            _delete_provider_file(db, pf_id)
    problems = list(out.get("problemas") or [])
    if r["status"] == "partial" or out.get("legibilidade") != "boa" or problems:
        doc.status = "partial"
        doc.problem = "; ".join(filter(None, [r.get("problem")] + problems))[:300] or "Processamento parcial"
    else:
        doc.status, doc.problem = "extracted", None
    db.add(AIRun(attendance_id=doc.attendance_id, document_id=doc.id, kind="doc_extraction", model=model,
                 input_fingerprint=doc.sha256, output_json=out, created_by=job.requested_by))
    audit(db, "document_extracted", doc.attendance_id, document_id=doc.id, status=doc.status, pages=doc.pages)


def _has_extraction(db, doc):
    return db.scalar(select(func.count()).select_from(AIRun).where(AIRun.document_id == doc.id, AIRun.kind == "doc_extraction")) > 0


def _delete_provider_file(db, file_id):
    pf = db.scalar(select(ProviderFile).where(ProviderFile.provider_file_id == file_id))
    try:
        ai.delete_provider_file(file_id)
        if pf:
            pf.deleted_at, pf.delete_status = now(), "deleted"
    except ai.AIError:
        if pf:
            pf.delete_status = "failed"
            enqueue(db, pf.attendance_id, "delete_provider_file", target_id=pf.id)


def run_delete_provider_file(db, job):
    pf = db.get(ProviderFile, job.target_id)
    if not pf or pf.delete_status == "deleted":
        return
    try:
        ai.delete_provider_file(pf.provider_file_id)
    except ai.AIError as e:
        raise StepError(str(e), True)
    pf.deleted_at, pf.delete_status = now(), "deleted"


def latest_extractions(db, att_id):
    docs = db.scalars(select(Document).where(Document.attendance_id == att_id, Document.status != "removed")).all()
    out = []
    for d in docs:
        run = db.scalar(select(AIRun).where(AIRun.document_id == d.id, AIRun.kind == "doc_extraction").order_by(AIRun.created_at.desc()))
        out.append({"doc": d, "run": run})
    return out


# ---------------- ficha ----------------
def run_summarize(db, job):
    att = db.get(Attendance, job.attendance_id)
    if not ai_quota_ok(db, job.requested_by):
        raise StepError("Limite diário de uso de IA atingido", retryable=False)
    transcript = att.transcript_revised if att.transcript_revised is not None else (att.transcript_original or "")
    segments = segment_transcript(transcript)
    ex = latest_extractions(db, att.id)
    extractions = [{"document_id": e["doc"].id, "name": e["doc"].original_name, "status": e["doc"].status,
                    "problem": e["doc"].problem, "pages": e["doc"].pages, "data": e["run"].output_json}
                   for e in ex if e["run"] is not None]
    if not segments and not extractions and not (att.notes or "").strip():
        raise StepError("Não há transcrição, anotações nem documentos analisados para gerar a ficha", retryable=False)
    try:
        ficha, model = ai.summarize(segments, att.notes or "", extractions)
    except ai.AIError as e:
        raise StepError(str(e), e.retryable)
    doc_pages = {e["doc"].id: e["doc"].pages for e in ex if e["run"] is not None}
    # documentos não processados aparecem como tal, mesmo que o modelo os omita
    listed = {d["document_id"] for d in ficha["documentos_analisados"]}
    for e in ex:
        if e["doc"].id not in listed:
            ficha["documentos_analisados"].append({"document_id": e["doc"].id, "tipo_documento": e["doc"].doc_type,
                                                   "cobertura": "nao_processado" if e["run"] is None else "parcial",
                                                   "observacao": e["doc"].problem})
    warnings = check_references(ficha, doc_pages, {sid for sid, _ in segments})
    vinc = [v for e in extractions for v in e["data"].get("cnis_vinculos", [])]
    calc = cnis_calculation(vinc) if vinc else None
    fp = "|".join([str(len(transcript)), ",".join(sorted(doc_pages)), str(len(att.notes or ""))])
    run = AIRun(attendance_id=att.id, kind="summary", model=model, input_fingerprint=fp,
                output_json={"ficha": ficha, "segmentos": segments, "calculos": {"cnis": calc}}, warnings=warnings,
                created_by=job.requested_by)
    db.add(run)
    db.flush()
    if att.ficha_revisada is None:  # primeira geração vira o rascunho editável; depois disso a IA nunca sobrescreve
        att.ficha_revisada = json.loads(json.dumps(ficha))
        att.ficha_revisada_base_run = run.id
    audit(db, "summary_generated", att.id, run_id=run.id, warnings=len(warnings))


# ---------------- descarte do áudio ----------------
def delete_audio(db, att, reason="finalized") -> bool:
    """Idempotente. Exclui todos os segmentos do armazenamento e arquivos de áudio no provedor (se houver).
    Registra data e resultado, sem conservar conteúdo."""
    segs = db.scalars(select(AudioSegment).where(AudioSegment.attendance_id == att.id)).all()
    ok = True
    for s in segs:
        if s.storage_key:
            try:
                if storage.delete(s.storage_key):
                    s.storage_key = None
                    s.deleted_at = now()
                    if s.status != "transcribed":
                        s.status = "expired" if reason == "ttl" else "deleted"
                else:
                    ok = False
            except Exception:
                ok = False
    for pf in db.scalars(select(ProviderFile).where(ProviderFile.attendance_id == att.id, ProviderFile.kind == "audio",
                                                    ProviderFile.delete_status != "deleted")).all():
        try:
            ai.delete_provider_file(pf.provider_file_id)
            pf.deleted_at, pf.delete_status = now(), "deleted"
        except ai.AIError:
            ok = False
    att.audio_deletion_attempts += 1
    if ok:
        att.audio_status = "expired" if reason == "ttl" else ("deleted" if segs else "none")
        att.audio_deleted_at = now()
        att.audio_deletion_result = f"ok: {len(segs)} segmento(s) excluído(s); transcrição envia o áudio diretamente (sem arquivo persistido no provedor)"
        audit(db, "audio_deleted", att.id, reason=reason, segments=len(segs))
    else:
        att.audio_status = "audio_deletion_pending"
        att.audio_deletion_result = "falha na exclusão; nova tentativa automática agendada"
        enqueue(db, att.id, "delete_audio", dedupe=f"delete_audio:{att.id}:{att.audio_deletion_attempts}", max_attempts=10)
        audit(db, "audio_deletion_failed", att.id, attempt=att.audio_deletion_attempts)
    return ok


def run_delete_audio(db, job):
    att = db.get(Attendance, job.attendance_id)
    if att.audio_status in ("deleted", "none", "expired"):
        return
    if not delete_audio(db, att):
        raise StepError("Exclusão do áudio falhou", True)


def sweep_expired_audio(db):
    """Rascunhos: áudio mantido só pelo prazo TEMP_AUDIO_TTL_HOURS; depois é excluído automaticamente."""
    limit = datetime.now(timezone.utc) - timedelta(hours=get_settings().temp_audio_ttl_hours)
    q = select(AudioSegment).where(AudioSegment.storage_key.is_not(None), AudioSegment.created_at < limit)
    att_ids = {s.attendance_id for s in db.scalars(q).all()}
    for aid in att_ids:
        att = db.get(Attendance, aid)
        if att.status != "finalized":
            delete_audio(db, att, reason="ttl")
    return len(att_ids)


STEP_STATUS = {"transcribe_segment": "transcribing", "extract_document": "analyzing_documents", "summarize": "generating_summary"}
RUNNERS = {"transcribe_segment": run_transcribe_segment, "extract_document": run_extract_document, "summarize": run_summarize,
           "delete_audio": run_delete_audio, "delete_provider_file": run_delete_provider_file}


def refresh_status(db, att):
    """Deriva o estado do atendimento a partir dos jobs. Não sai de 'finalized'."""
    if att.status in ("finalized", "recording", "uploading"):
        return
    jobs = db.scalars(select(Job).where(Job.attendance_id == att.id, Job.kind.in_(list(STEP_STATUS)))).all()
    active = [j for j in jobs if j.status in ("queued", "running")]
    failed = [j for j in jobs if j.status == "failed"]
    if active:
        order = ["transcribe_segment", "extract_document", "summarize"]
        k = min((j.kind for j in active), key=order.index)
        att.status = STEP_STATUS[k]
    elif failed:
        att.status = "failed"
        att.failed_step = failed[-1].kind
        att.last_error = failed[-1].last_error
    elif att.ficha_revisada is not None:
        att.status, att.failed_step, att.last_error = "awaiting_review", None, None
    else:
        att.status = "draft"
