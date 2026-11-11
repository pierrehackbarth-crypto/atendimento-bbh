"""Cria o .env a partir do .env.example com chave de criptografia nova e ajustes para uso local (localhost)."""
from cryptography.fernet import Fernet
import os, re
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(base, ".env.example"), encoding="utf-8").read()
key = Fernet.generate_key().decode()
src = re.sub(r"^STORAGE_ENCRYPTION_KEY=.*$", f"STORAGE_ENCRYPTION_KEY={key}", src, flags=re.M)
src = re.sub(r"^SESSION_COOKIE_SECURE=.*$", "SESSION_COOKIE_SECURE=false", src, flags=re.M)
src = re.sub(r"^RUN_WORKER_IN_PROCESS=.*$", "RUN_WORKER_IN_PROCESS=true", src, flags=re.M)
src += ("\n# IMPORTANTE: guarde uma copia desta chave em local seguro (fora deste computador).\n"
        "# Sem ela os documentos guardados nao podem ser lidos.\n")
open(os.path.join(base, ".env"), "w", encoding="utf-8").write(src)
print("Configuracao criada (.env).")
