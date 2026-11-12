"""Controle de usuários: só o administrador cadastra, bloqueia, troca senha e define o que cada pessoa acessa."""
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from .models import User, SessionToken
from .security import get_db, current_user, hash_password
from .permissions import PERMS, ROLES, ROLE_DEFAULTS, effective
from .audit import audit

router = APIRouter(prefix="/api/admin")
EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PW = 10


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Somente o administrador")
    return user


def _view(u: User):
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
            "custom": u.perms is not None, "perms": effective(u), "created_at": u.created_at}


def _clean_perms(p):
    if p is None:
        return None
    if not isinstance(p, dict):
        raise HTTPException(400, "Permissões inválidas")
    return {k: bool(p[k]) for k in PERMS if k in p}


def _check_pw(pw: str):
    if len(pw or "") < MIN_PW:
        raise HTTPException(400, f"A senha precisa ter pelo menos {MIN_PW} caracteres")


def _drop_sessions(db, uid):
    db.execute(delete(SessionToken).where(SessionToken.user_id == uid))


def _admins_left(db, except_id):
    return db.scalars(select(User).where(User.role == "admin", User.active == True, User.id != except_id)).first()  # noqa: E712


@router.get("/permissions")
def catalog(user=Depends(admin_user)):
    return {"perms": [{"key": k, "label": v[0], "help": v[1]} for k, v in PERMS.items()],
            "roles": list(ROLES), "defaults": {**ROLE_DEFAULTS, "admin": {k: True for k in PERMS}}}


@router.get("/users")
def list_users(user=Depends(admin_user), db=Depends(get_db)):
    return [_view(u) for u in db.scalars(select(User).order_by(User.active.desc(), User.name))]


class NewUser(BaseModel):
    email: str
    name: str
    role: str = "advogado"
    password: str
    perms: dict | None = None


@router.post("/users")
def create_user(body: NewUser, user=Depends(admin_user), db=Depends(get_db)):
    email = body.email.strip().lower()
    if not EMAIL_RX.match(email):
        raise HTTPException(400, "E-mail inválido")
    if not body.name.strip():
        raise HTTPException(400, "Informe o nome")
    if body.role not in ROLES:
        raise HTTPException(400, "Papel inválido")
    _check_pw(body.password)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Já existe usuário com esse e-mail")
    u = User(email=email, name=body.name.strip()[:200], role=body.role, password_hash=hash_password(body.password),
             perms=_clean_perms(body.perms))
    db.add(u)
    db.flush()
    audit(db, "user_created", user_id=user.id, target=u.id, role=u.role)
    db.commit()
    return _view(u)


class EditUser(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    perms: dict | None = None
    reset_perms: bool = False   # volta ao padrão do papel


@router.patch("/users/{uid}")
def edit_user(uid: str, body: EditUser, user=Depends(admin_user), db=Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
    losing_admin = (body.role is not None and body.role != "admin") or body.active is False
    if u.role == "admin" and losing_admin and not _admins_left(db, u.id):
        raise HTTPException(400, "Precisa haver ao menos um administrador ativo")
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(400, "Informe o nome")
        u.name = body.name.strip()[:200]
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(400, "Papel inválido")
        u.role = body.role
    if body.reset_perms:
        u.perms = None
    elif body.perms is not None:
        u.perms = _clean_perms(body.perms)
    if body.active is not None and body.active != u.active:
        u.active = body.active
        if not u.active:
            _drop_sessions(db, u.id)   # bloqueado sai na hora de todos os aparelhos
    audit(db, "user_updated", user_id=user.id, target=u.id)
    db.commit()
    return _view(u)


class NewPassword(BaseModel):
    password: str


@router.post("/users/{uid}/password")
def set_password(uid: str, body: NewPassword, user=Depends(admin_user), db=Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Usuário não encontrado")
    _check_pw(body.password)
    u.password_hash = hash_password(body.password)
    if u.id != user.id:
        _drop_sessions(db, u.id)
    audit(db, "user_password_set", user_id=user.id, target=u.id)
    db.commit()
    return {"ok": True}
