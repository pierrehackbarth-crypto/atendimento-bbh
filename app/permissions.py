"""Permissões por usuário.

O administrador define, para cada pessoa, o que ela pode fazer. Quem não tem ajuste próprio
segue o padrão do papel (admin, advogado ou assistente). O administrador sempre pode tudo.
"""
from fastapi import HTTPException

# chave -> (rótulo mostrado na tela de usuários, explicação)
PERMS = {
    "fichas_ver": ("Ver fichas", "Abrir e consultar fichas de atendimento"),
    "fichas_todas": ("Ver fichas de todos", "Sem isso, vê só as fichas que criou ou em que é o atendente"),
    "fichas_editar": ("Criar e editar fichas", "Criar fichas novas e alterar as existentes"),
    "fichas_excluir": ("Excluir fichas", "Mandar fichas para a lixeira"),
    "lixeira": ("Lixeira", "Ver a lixeira e restaurar fichas excluídas"),
    "backup": ("Backup", "Exportar e importar o backup das fichas"),
    "base_clientes": ("Base de clientes", "Buscar clientes na base do escritório (17 mil cadastros)"),
    "ia": ("Usar IA", "Ler documentos e transcrições com a IA"),
    "tramitacao": ("Tramitação Inteligente", "Buscar cliente e processos no Tramitação"),
    "gravacao": ("Gravação e análise", "Usar o módulo de gravação, transcrição e análise de documentos"),
    "docs_sensiveis": ("Documentos médicos", "Abrir documentos médicos e outros sensíveis"),
}

ROLE_DEFAULTS = {
    "advogado": {k: True for k in PERMS},
    "assistente": {**{k: True for k in PERMS}, "fichas_excluir": False, "lixeira": False, "backup": False,
                   "docs_sensiveis": False},
}
ROLES = ("admin", "advogado", "assistente")


def effective(user) -> dict:
    if user.role == "admin":
        return {k: True for k in PERMS}
    base = dict(ROLE_DEFAULTS.get(user.role, {k: False for k in PERMS}))
    if user.perms is None:
        # contas antigas: respeita o ajuste de documentos sensíveis que já existia
        base["docs_sensiveis"] = base["docs_sensiveis"] and bool(user.can_view_sensitive)
    else:
        base.update({k: bool(v) for k, v in user.perms.items() if k in PERMS})
    return base


def has(user, perm: str) -> bool:
    return effective(user).get(perm, False)


def require(user, perm: str):
    if not has(user, perm):
        raise HTTPException(403, f"Sem permissão: {PERMS[perm][0]}")
