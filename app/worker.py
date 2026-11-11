"""Worker de tarefas assíncronas com estado persistido no banco e retentativas com espera exponencial."""
import logging, threading, time
from datetime import timedelta
from sqlalchemy import select, update
from .db import SessionLocal
from .config import get_settings
from .models import Job, Attendance, now
from . import pipeline

log = logging.getLogger("atendimento.worker")
_last_sweep = 0.0


def claim(db):
    j = db.scalar(select(Job).where(Job.status == "queued", Job.next_run_at <= now()).order_by(Job.created_at).limit(1))
    if not j:
        return None
    # compare-and-set: só um worker assume o job
    res = db.execute(update(Job).where(Job.id == j.id, Job.status == "queued").values(status="running", attempts=Job.attempts + 1))
    db.commit()
    if res.rowcount != 1:
        return None
    db.refresh(j)
    return j


def run_one() -> bool:
    db = SessionLocal()
    try:
        j = claim(db)
        if not j:
            return False
        att = db.get(Attendance, j.attendance_id)
        pipeline.refresh_status(db, att)
        db.commit()
        try:
            pipeline.RUNNERS[j.kind](db, j)
            j.status, j.last_error = "done", None
        except pipeline.StepError as e:
            db.rollback()
            j = db.get(Job, j.id)
            j.last_error = str(e)[:300]
            if e.retryable and j.attempts < j.max_attempts:
                j.status = "queued"
                j.next_run_at = now() + timedelta(seconds=min(600, 5 * 3 ** j.attempts))
            else:
                j.status = "failed"
        except Exception as e:  # erro inesperado: registra só o tipo, nunca conteúdo
            db.rollback()
            j = db.get(Job, j.id)
            j.last_error = f"Erro interno ({type(e).__name__})"
            log.error("job %s falhou: %s", j.id, type(e).__name__)
            j.status = "queued" if j.attempts < j.max_attempts else "failed"
            j.next_run_at = now() + timedelta(seconds=30)
        if j.kind == "extract_document" and j.status != "done":
            # a falha desfaz a transação; o documento não pode ficar "analisando" para sempre
            from .models import Document
            d = db.get(Document, j.target_id)
            if d and d.status == "extracting":
                d.status = "failed" if j.status == "failed" else "uploaded"
                if j.status == "failed":
                    d.problem = (j.last_error or "Falha na análise")[:300]
        att = db.get(Attendance, j.attendance_id)
        pipeline.refresh_status(db, att)
        db.commit()
        return True
    finally:
        db.close()


def sweep():
    db = SessionLocal()
    try:
        pipeline.sweep_expired_audio(db)
        db.commit()
    finally:
        db.close()


def loop(stop: threading.Event):
    global _last_sweep
    s = get_settings()
    while not stop.is_set():
        try:
            worked = run_one()
            if time.time() - _last_sweep > 600:
                sweep()
                _last_sweep = time.time()
        except Exception as e:
            log.error("worker: %s", type(e).__name__)
            worked = False
        if not worked:
            stop.wait(s.worker_poll_seconds)


def drain(max_jobs=100):
    """Para testes: executa todos os jobs prontos."""
    n = 0
    while n < max_jobs and run_one():
        n += 1
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop(threading.Event())
