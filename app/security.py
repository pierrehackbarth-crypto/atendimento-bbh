import hashlib, secrets
from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from .db import SessionLocal
from .config import get_settings
from .models import User, SessionToken, Client, ClientAccess, Attendance, Document

COOKIE = "sid"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(12)).decode()


def check_password(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except ValueError:
        return False


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_session(db, user: User, resp: Response) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    s = get_settings()
    db.add(SessionToken(token_hash=_th(token), user_id=user.id, csrf=csrf,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=s.session_hours)))
    db.commit()
    resp.set_cookie(COOKIE, token, httponly=True, secure=s.session_cookie_secure, samesite="strict",
                    max_age=s.session_hours * 3600, path="/")
    return csrf


def current_user(request: Request, db=Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Sessão não iniciada")
    st = db.get(SessionToken, _th(token))
    if not st or st.expires_at.replace(tzinfo=st.expires_at.tzinfo or timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(401, "Sessão expirada")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), st.csrf):
            raise HTTPException(403, "Token CSRF inválido")
    user = db.get(User, st.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Usuário inativo")
    request.state.csrf = st.csrf
    return user


def can_access_client(db, user: User, client: Client) -> bool:
    if user.role == "admin" or client.owner_id == user.id:
        return True
    return db.get(ClientAccess, (client.id, user.id)) is not None


def load_client(db, user: User, client_id: str) -> Client:
    c = db.get(Client, client_id)
    # 404 também para acesso negado, para não revelar existência
    if not c or not can_access_client(db, user, c):
        raise HTTPException(404, "Cliente não encontrado")
    return c


def load_attendance(db, user: User, att_id: str) -> Attendance:
    a = db.get(Attendance, att_id)
    if not a:
        raise HTTPException(404, "Atendimento não encontrado")
    c = db.get(Client, a.client_id)
    if not c or not can_access_client(db, user, c):
        raise HTTPException(404, "Atendimento não encontrado")
    return a


def check_sensitive(user: User, doc: Document):
    from .permissions import has
    if doc.sensitive and not has(user, "docs_sensiveis"):
        raise HTTPException(403, "Sem permissão para documentos médicos/sensíveis")


def gravacao_user(user: User = Depends(current_user)) -> User:
    """Usuário do módulo de gravação/análise: exige a permissão "gravacao"."""
    from .permissions import require
    require(user, "gravacao")
    return user
