"""JSON Schemas (Structured Outputs, modo strict) e validação de referências no servidor."""
import re
from datetime import date
import jsonschema


def _n(t):  # tipo anulável
    return {"type": [t, "null"]}


def obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props.keys()), "additionalProperties": False}


FONTE = obj({
    "tipo": {"type": "string", "enum": ["documento", "transcricao", "anotacao"]},
    "document_id": _n("string"),
    "pagina": _n("integer"),
    "segmento": _n("string"),
    "trecho": _n("string"),
})
FONTES = {"type": "array", "items": FONTE}


def arr(props):
    return {"type": "array", "items": obj(props)}


FICHA_SCHEMA = obj({
    "motivo_consulta": {"type": "string"},
    "objetivo_cliente": {"type": "string"},
    "relato_cronologico": arr({"data": _n("string"), "descricao": {"type": "string"}, "fontes": FONTES}),
    "datas_relevantes": arr({"data": {"type": "string"}, "evento": {"type": "string"}, "fontes": FONTES}),
    "beneficios_requerimentos_processos": arr({
        "tipo": {"type": "string"}, "numero": _n("string"), "der": _n("string"), "dib": _n("string"),
        "situacao": _n("string"), "motivo_decisao": _n("string"), "fontes": FONTES}),
    "documentos_analisados": arr({
        "document_id": {"type": "string"}, "tipo_documento": {"type": "string"},
        "cobertura": {"type": "string", "enum": ["completa", "parcial", "nao_processado"]},
        "observacao": _n("string")}),
    "informacoes_documentadas": arr({
        "categoria": {"type": "string"}, "descricao": {"type": "string"}, "valor_original": _n("string"), "fontes": FONTES}),
    "orientacoes_advogado": arr({"descricao": {"type": "string"}, "fontes": FONTES}),
    "divergencias": arr({
        "assunto": {"type": "string"}, "versao_cliente": {"type": "string"}, "versao_documento": {"type": "string"},
        "fontes": FONTES}),
    "documentos_pendentes": arr({"documento": {"type": "string"}, "motivo": _n("string"), "fontes": FONTES}),
    "providencias_discutidas": arr({"descricao": {"type": "string"}, "responsavel": _n("string"), "fontes": FONTES}),
    "prazos_mencionados": arr({"descricao": {"type": "string"}, "data": _n("string"), "fontes": FONTES}),
    "pontos_para_confirmacao": arr({"ponto": {"type": "string"}, "motivo": _n("string"), "fontes": FONTES}),
    "informacoes_ausentes": {"type": "array", "items": {"type": "string"}},
})

REF = {"pagina": _n("integer"), "trecho": _n("string")}
DOC_EXTRACTION_SCHEMA = obj({
    "tipo_documento": {"type": "string", "enum": ["cnis", "medico", "tempo_contribuicao", "administrativo", "outro"]},
    "legibilidade": {"type": "string", "enum": ["boa", "parcial", "ilegivel"]},
    "paginas_analisadas": {"type": "array", "items": {"type": "integer"}},
    "problemas": {"type": "array", "items": {"type": "string"}},
    "cnis_vinculos": arr({"empregador": {"type": "string"}, "cnpj_cpf": _n("string"), "inicio": _n("string"),
                          "fim": _n("string"), "tipo": _n("string"), "indicadores": {"type": "array", "items": {"type": "string"}}, **REF}),
    "contribuicoes": arr({"competencia_inicio": _n("string"), "competencia_fim": _n("string"), "categoria": _n("string"),
                          "observacao": _n("string"), **REF}),
    "medico": arr({"data": _n("string"), "profissional": _n("string"), "crm": _n("string"),
                   "diagnosticos": {"type": "array", "items": {"type": "string"}}, "cids": {"type": "array", "items": {"type": "string"}},
                   "limitacoes": _n("string"), "conclusao_documento": _n("string"), **REF}),
    "tempo": arr({"periodo_inicio": _n("string"), "periodo_fim": _n("string"), "descricao": {"type": "string"},
                  "total_apresentado": _n("string"), "metodologia": _n("string"), **REF}),
    "administrativo": arr({"beneficio": _n("string"), "nb": _n("string"), "der": _n("string"), "dib": _n("string"),
                           "decisao": _n("string"), "motivo": _n("string"), **REF}),
    "outros": arr({"descricao": {"type": "string"}, "data": _n("string"), **REF}),
})


def validate(data, schema):
    jsonschema.validate(data, schema)


def empty_ficha() -> dict:
    out = {}
    for k, v in FICHA_SCHEMA["properties"].items():
        out[k] = "" if v.get("type") == "string" else []
    return out


# ---------- segmentação determinística da transcrição (referências T001, T002...) ----------
def segment_transcript(text: str, max_chars: int = 600):
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    segs = []
    for p in parts:
        while len(p) > max_chars:
            cut = p.rfind(". ", 0, max_chars)
            cut = cut + 1 if cut > 200 else max_chars
            segs.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            segs.append(p)
    return [(f"T{i + 1:03d}", s) for i, s in enumerate(segs)]


def check_references(ficha: dict, doc_pages: dict, seg_ids: set) -> list:
    """Remove fontes que não existem (documento/página/segmento) e devolve avisos. Não altera fatos."""
    warnings = []
    for key, val in ficha.items():
        if not isinstance(val, list):
            continue
        for i, item in enumerate(val):
            if not isinstance(item, dict) or "fontes" not in item:
                continue
            ok = []
            for f in item["fontes"]:
                t = f.get("tipo")
                if t == "documento":
                    did, pg = f.get("document_id"), f.get("pagina")
                    if did not in doc_pages:
                        warnings.append(f"{key}[{i}]: referência a documento inexistente removida")
                        continue
                    if pg is not None and not (1 <= pg <= (doc_pages[did] or 1)):
                        warnings.append(f"{key}[{i}]: página {pg} inexistente no documento removida")
                        f = dict(f, pagina=None)
                elif t == "transcricao":
                    if f.get("segmento") not in seg_ids:
                        warnings.append(f"{key}[{i}]: segmento de transcrição inexistente removido")
                        continue
                ok.append(f)
            item["fontes"] = ok
    return warnings


# ---------- cálculo determinístico: vínculos do CNIS ----------
def parse_br_date(s):
    if not s:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"(\d{2})/(\d{4})", s)
    if m:
        try:
            return date(int(m.group(2)), int(m.group(1)), 1)
        except ValueError:
            return None
    return None


def cnis_calculation(vinculos: list) -> dict:
    """Une períodos sobrepostos e soma dias corridos. Verificável: devolve os intervalos usados."""
    ivs, ignored = [], []
    for v in vinculos:
        a, b = parse_br_date(v.get("inicio")), parse_br_date(v.get("fim"))
        if not a or not b or b < a:
            ignored.append(v.get("empregador") or "?")
            continue
        ivs.append((a, b, v.get("empregador") or "?"))
    ivs.sort()
    merged, overlaps = [], []
    for a, b, n in ivs:
        if merged and a <= merged[-1][1]:
            overlaps.append({"vinculo": n, "inicio": a.strftime("%d/%m/%Y"), "sobrepoe_ate": min(b, merged[-1][1]).strftime("%d/%m/%Y")})
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    days = sum((b - a).days + 1 for a, b in merged)
    y, rem = divmod(days, 365)
    m, d = divmod(rem, 30)
    return {"metodo": "dias corridos dos períodos com início e fim, unindo sobreposições (365 dias = 1 ano; 30 dias = 1 mês)",
            "intervalos": [[a.strftime("%d/%m/%Y"), b.strftime("%d/%m/%Y")] for a, b in merged],
            "total_dias": days, "total_aproximado": f"{y} anos, {m} meses e {d} dias",
            "sobreposicoes": overlaps, "vinculos_sem_datas": ignored}
