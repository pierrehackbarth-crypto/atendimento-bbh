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
    # módulo amarelo – Controle de Prazos
    "prazos": ("Abrir o Controle de Prazos", "Ver todos os prazos e lançar providência, observações e ED nos da própria equipe (e nos \"A definir\")"),
    "prazos_importar": ("Importar planilhas do eproc", "Trazer para o sistema as planilhas de intimações do eproc"),
    "prazos_exportar": ("Exportar Excel", "Baixar os prazos em planilha"),
    "prazos_equipe": ("Definir a equipe do prazo", "Escolher Alfa ou Beta em cada prazo"),
    "prazos_editar_outra": ("Editar prazos da outra equipe", "Providência, observações e ED nos prazos da outra equipe"),
    "prazos_excluir_propria": ("Excluir prazos da própria equipe", "Apagar um prazo da própria equipe"),
    "prazos_excluir_outra": ("Excluir prazos da outra equipe", "Apagar um prazo da outra equipe"),
    "prazos_baixa": ("Marcar prazo como cumprido", "Marcar como cumprido ou reabrir um prazo"),
    "prazos_configurar": ("Configurações dos prazos", "Regras de equipe, feriados, comarcas e links dos tribunais"),
    "prazos_produtividade": ("Ver a produtividade", "Relatório do que cada pessoa fez nos prazos"),
}

# em que módulo do THANOS cada permissão aparece na tela de usuários
GRUPO = {k: ("Controle de Prazos (joia amarela)" if k.startswith("prazos") else "Atendimento (joia vermelha)") for k in PERMS}
# padrão do sistema de prazos antigo: todos veem e exportam; o resto o administrador libera pessoa por pessoa
_PRAZOS_PADRAO = {k: k in ("prazos", "prazos_exportar") for k in PERMS if k.startswith("prazos")}

ROLE_DEFAULTS = {
    "advogado": {**{k: True for k in PERMS}, **_PRAZOS_PADRAO},
    "assistente": {**{k: True for k in PERMS}, "fichas_excluir": False, "lixeira": False, "backup": False,
                   "docs_sensiveis": False, **_PRAZOS_PADRAO},
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
