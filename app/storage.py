"""Armazenamento privado: nomes internos aleatórios, conteúdo criptografado (Fernet/AES), sem URL pública."""
import os, secrets, hashlib
from cryptography.fernet import Fernet
from .config import get_settings

_fernet = None


def _f():
    global _fernet
    if _fernet is None:
        key = get_settings().storage_encryption_key
        if not key:
            raise RuntimeError("STORAGE_ENCRYPTION_KEY não configurada")
        _fernet = Fernet(key.encode())
    return _fernet


def reset():
    global _fernet
    _fernet = None


def _path(key: str) -> str:
    if not key or "/" in key or "\\" in key or ".." in key:
        raise ValueError("chave de armazenamento inválida")
    st = get_settings()
    base = os.path.abspath(st.storage_audio_dir if key.startswith("a_") else st.storage_dir)
    os.makedirs(os.path.join(base, key[:2]), exist_ok=True)
    return os.path.join(base, key[:2], key)


def put(data: bytes, prefix: str) -> str:
    key = f"{prefix}{secrets.token_hex(16)}"
    p = _path(key)
    tmp = p + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(_f().encrypt(data))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    os.chmod(p, 0o600)
    return key


def get(key: str) -> bytes:
    with open(_path(key), "rb") as fh:
        return _f().decrypt(fh.read())


def exists(key: str) -> bool:
    return os.path.exists(_path(key))


def delete(key: str) -> bool:
    """Idempotente: ausência do arquivo conta como excluído."""
    p = _path(key)
    try:
        os.remove(p)
    except FileNotFoundError:
        pass
    return not os.path.exists(p)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
