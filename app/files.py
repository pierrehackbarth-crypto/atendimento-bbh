"""Validação de arquivos (extensão, MIME, assinatura, tamanho) e extração de PDFs/imagens."""
import io, re, json
import pymupdf
from fastapi import HTTPException

DOC_TYPES = {
    "pdf": ({"application/pdf"}, lambda b: b[:5] == b"%PDF-"),
    "jpg": ({"image/jpeg"}, lambda b: b[:3] == b"\xff\xd8\xff"),
    "jpeg": ({"image/jpeg"}, lambda b: b[:3] == b"\xff\xd8\xff"),
    "png": ({"image/png"}, lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"),
}
AUDIO_TYPES = {
    "webm": ({"audio/webm", "video/webm"}, lambda b: b[:4] == b"\x1a\x45\xdf\xa3"),
    "ogg": ({"audio/ogg"}, lambda b: b[:4] == b"OggS"),
    "m4a": ({"audio/mp4", "audio/x-m4a", "audio/m4a"}, lambda b: b[4:8] == b"ftyp"),
    "mp4": ({"audio/mp4", "video/mp4"}, lambda b: b[4:8] == b"ftyp"),
    "wav": ({"audio/wav", "audio/x-wav", "audio/wave"}, lambda b: b[:4] == b"RIFF" and b[8:12] == b"WAVE"),
}
# Formatos aceitos pela API de transcrição (documentação): mp3, mp4, mpeg, mpga, m4a, wav, webm. "ogg" é convertido? -> não aceito.
TRANSCRIBABLE = {"webm", "m4a", "mp4", "wav"}

DOC_TYPE_HINTS = [
    ("cnis", r"cnis|extrato previdenci"), ("medico", r"laudo|exame|atestado|receita|relat[oó]rio m[eé]d|cid|crm"),
    ("tempo", r"contagem|tempo de (servi|contribui)|simula"), ("administrativo", r"carta|indeferi|concess|comunicado|decis"),
]


def _ext(name: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", name or "")
    return m.group(1).lower() if m else ""


def validate(name: str, mime: str, data: bytes, table: dict, max_bytes: int) -> str:
    ext = _ext(name)
    if ext not in table:
        raise HTTPException(415, f"Formato não aceito: .{ext or '?'}")
    mimes, sig = table[ext]
    if (mime or "").split(";")[0].strip().lower() not in mimes:
        raise HTTPException(415, f"Tipo de arquivo (MIME) incompatível com .{ext}")
    if len(data) == 0:
        raise HTTPException(400, "Arquivo vazio")
    if len(data) > max_bytes:
        raise HTTPException(413, f"Arquivo acima do limite de {max_bytes // (1024 * 1024)} MB")
    if not sig(data):
        raise HTTPException(415, "Conteúdo do arquivo não corresponde à extensão (assinatura inválida)")
    return ext


def guess_doc_type(name: str, text: str = "") -> str:
    hay = (name + " " + text[:3000]).lower()
    for t, rx in DOC_TYPE_HINTS:
        if re.search(rx, hay):
            return t
    return "outro"


def safe_name(name: str) -> str:
    name = re.sub(r"[\x00-\x1f/\\]+", "_", name or "arquivo")
    return name[-150:]


MIN_TEXT_CHARS = 40


def extract_pdf(data: bytes) -> dict:
    """Extrai texto por página na ordem de leitura. Não executa JavaScript/anexos do PDF.
    Retorna {status, problem, pages:[{page, text, needs_visual}], page_images:{n: png}}"""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return {"status": "failed", "problem": "PDF corrompido ou ilegível", "pages": []}
    try:
        if doc.needs_pass or doc.is_encrypted and not doc.authenticate(""):
            return {"status": "failed", "problem": "PDF protegido por senha", "pages": []}
        pages, images, errors = [], {}, []
        for i in range(doc.page_count):
            try:
                pg = doc.load_page(i)
                text = pg.get_text("text", sort=True).strip()
                needs_visual = len(text) < MIN_TEXT_CHARS
                if needs_visual:
                    pix = pg.get_pixmap(dpi=150)
                    images[i + 1] = pix.tobytes("png")
                pages.append({"page": i + 1, "text": text, "needs_visual": needs_visual})
            except Exception:
                errors.append(i + 1)
                pages.append({"page": i + 1, "text": "", "needs_visual": False, "error": True})
        status = "partial" if errors else "extracted"
        problem = f"Páginas não processadas: {', '.join(map(str, errors))}" if errors else None
        return {"status": status, "problem": problem, "pages": pages, "page_images": images, "page_count": doc.page_count}
    finally:
        doc.close()


def check_image(data: bytes) -> dict:
    try:
        doc = pymupdf.open(stream=data)
        ok = doc.page_count >= 1
        doc.close()
    except Exception:
        ok = False
    if not ok:
        return {"status": "failed", "problem": "Imagem corrompida ou ilegível", "pages": []}
    return {"status": "extracted", "problem": None, "pages": [{"page": 1, "text": "", "needs_visual": True}], "page_count": 1}
