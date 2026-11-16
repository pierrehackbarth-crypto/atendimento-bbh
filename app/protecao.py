"""Proteções para quando o THANOS fica aberto na internet.

- Limite de tentativas de login: 5 erros seguidos no mesmo e-mail bloqueiam esse e-mail por 15 minutos.
- No máximo 2 conferências de senha ao mesmo tempo no servidor todo (cada uma leva ~0,3 s), o que segura
  tentativas em massa. Não há bloqueio por IP: atrás do Tailscale Funnel todo acesso chega como 127.0.0.1
  (o Funnel não informa o IP real), e bloquear por IP trancaria o escritório inteiro.
- Política de senha: mínimo de 10 caracteres, com letras e números, sem conter o próprio e-mail
  e fora da lista das senhas mais usadas.
Os contadores ficam na memória do servidor (um processo só) e zeram se o serviço reiniciar.
"""
import re, threading, time
from fastapi import HTTPException, Request

JANELA = 15 * 60
MAX_EMAIL = 5
SENHAS_SIMULTANEAS = threading.BoundedSemaphore(2)
_lock = threading.Lock()
_falhas: dict[str, list[float]] = {}
_bloqueio: dict[str, float] = {}


def ip_de(request: Request) -> str:
    """Só para o registro de auditoria (não é confiável para bloquear: o cabeçalho pode ser forjado)."""
    xf = request.headers.get("x-forwarded-for", "")
    if xf:
        return "xff:" + xf.split(",")[0].strip()[:60]
    return request.client.host if request.client else "?"


def _limpa(chave, agora):
    _falhas[chave] = [t for t in _falhas.get(chave, []) if agora - t < JANELA]


def verificar(email: str):
    """Levanta 429 se o e-mail estiver bloqueado."""
    agora = time.time()
    with _lock:
        for chave in ("e:" + email,):
            ate = _bloqueio.get(chave, 0)
            if ate > agora:
                minutos = max(1, int((ate - agora) // 60) + 1)
                raise HTTPException(429, f"Muitas tentativas de entrada. Tente de novo em {minutos} minuto(s).")


def registrar_falha(email: str):
    agora = time.time()
    with _lock:
        for chave, limite in (("e:" + email, MAX_EMAIL),):
            _limpa(chave, agora)
            _falhas[chave].append(agora)
            if len(_falhas[chave]) >= limite:
                _bloqueio[chave] = agora + JANELA
                _falhas[chave] = []


def registrar_sucesso(email: str):
    with _lock:
        _falhas.pop("e:" + email, None)
        _bloqueio.pop("e:" + email, None)


def zerar():
    with _lock:
        _falhas.clear()
        _bloqueio.clear()


COMUNS = {"1234567890", "12345678910", "0123456789", "qwertyuiop", "senha12345", "senha123456", "password123",
          "abc1234567", "1q2w3e4r5t", "mudar12345", "admin12345", "bussehackbarth", "thanos1234", "blumenau123"}
MIN_SENHA = 10


def problema_senha(senha: str, email: str = "") -> str | None:
    s = senha or ""
    if len(s) < MIN_SENHA:
        return f"A senha precisa ter pelo menos {MIN_SENHA} caracteres"
    if not re.search(r"[A-Za-zÀ-ÿ]", s) or not re.search(r"\d", s):
        return "A senha precisa ter letras e números"
    if s.lower() in COMUNS or len(set(s)) < 5:
        return "Essa senha é fácil demais de adivinhar"
    local = (email or "").split("@")[0].lower()
    if len(local) >= 4 and local in s.lower():
        return "A senha não pode conter o e-mail"
    return None
