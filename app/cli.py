"""Administração:
  python -m app.cli create-user EMAIL NOME PAPEL        (papel: admin | advogado | assistente)
  python -m app.cli set-password EMAIL                  (troca a senha)
  python -m app.cli deactivate-user EMAIL               (bloqueia o acesso)
  python -m app.cli list-users
  python -m app.cli import-ficha ARQUIVO                (backup .json da ficha, ou base de clientes .json/.json.gz)
  python -m app.cli create-client NOME CPF EMAIL_RESPONSAVEL  |  sweep"""
import sys, getpass
from sqlalchemy import select
from .db import SessionLocal
from .models import User, Client
from .security import hash_password
from . import worker


def main(argv):
    db = SessionLocal()
    cmd = argv[0] if argv else ""
    if cmd == "create-user":
        email, name, role = argv[1].lower(), argv[2], (argv[3] if len(argv) > 3 else "advogado")
        pw = getpass.getpass("Senha: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
        if len(pw) < 10:
            sys.exit("Senha precisa ter ao menos 10 caracteres")
        if role not in ("admin", "advogado", "assistente"):
            sys.exit("Papel inválido: use admin, advogado ou assistente")
        if db.scalar(select(User).where(User.email == email)):
            sys.exit("Já existe usuário com este e-mail")
        db.add(User(email=email, name=name, role=role, password_hash=hash_password(pw)))
        db.commit()
        print("Usuário criado:", email, role)
    elif cmd == "create-client":
        owner = db.scalar(select(User).where(User.email == argv[3].lower()))
        c = Client(name=argv[1], cpf=argv[2] or None, owner_id=owner.id)
        db.add(c)
        db.commit()
        print("Cliente criado:", c.id)
    elif cmd in ("set-password", "deactivate-user"):
        u = db.scalar(select(User).where(User.email == argv[1].lower()))
        if not u:
            sys.exit("Usuário não encontrado")
        if cmd == "set-password":
            pw = getpass.getpass("Nova senha: ") if sys.stdin.isatty() else sys.stdin.readline().strip()
            if len(pw) < 10:
                sys.exit("Senha precisa ter ao menos 10 caracteres")
            u.password_hash = hash_password(pw)
        else:
            u.active = False
            from .models import SessionToken
            for st in db.scalars(select(SessionToken).where(SessionToken.user_id == u.id)).all():
                db.delete(st)
        db.commit()
        print("Feito:", u.email)
    elif cmd == "list-users":
        for u in db.scalars(select(User).order_by(User.name)).all():
            print(f"{u.email:40} {u.role:11} {'ativo' if u.active else 'BLOQUEADO':9} {u.name}")
    elif cmd == "import-ficha":
        from .ficha_import import import_file
        print(import_file(db, argv[1]))
    elif cmd == "sweep":
        worker.sweep()
        print("Limpeza de áudios expirados executada")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
