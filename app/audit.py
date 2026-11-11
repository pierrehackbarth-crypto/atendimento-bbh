import logging
from .models import AuditEvent

log = logging.getLogger("atendimento")


def audit(db, action: str, attendance_id=None, user_id=None, **meta):
    """Registra apenas metadados. Nunca passe conteúdo de transcrição, documento ou áudio."""
    db.add(AuditEvent(action=action, attendance_id=attendance_id, user_id=user_id, meta=meta or None))
    log.info("audit action=%s attendance=%s", action, attendance_id)
