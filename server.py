"""SuperTonic — servidor HTTP (FastAPI) com UI web, rota /usar e API key opcional.

Camadas:
* ``supertonic.server.app.create_app`` fornece /v1/* (TTS nativo + alias OpenAI).
* Este módulo adiciona:
  - ``GET /``            → interface web (pasta ``static/``)
  - ``GET /health``      → healthcheck do Railway
  - ``POST /usar``       → rota usada pela UI: texto | arquivo | link de vídeo
  - ``GET /api/voices``  → lista de vozes disponíveis
  - Middleware de API key (``API_KEY``) protegendo /v1/*.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from supertonic.server.app import create_app
from supertonic.server.audio import SUPPORTED_FORMATS, encode_audio, format_to_mime
from supertonic.server.routes import UnknownVoice, _do_synthesize

logger = logging.getLogger("supertonic.ui")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# Configuração via ambiente
# ---------------------------------------------------------------------------
MODEL = os.environ.get("SUPERSONIC_MODEL", os.environ.get("SUPERTONIC_MODEL", "supertonic-3"))
DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "pt")
MAX_TEXT_CHARS = int(os.environ.get("MAX_TEXT_CHARS", "40000"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "60"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

# Rotas públicas (sem API key). A UI e /usar ficam abertas; /v1/* exige chave.
PUBLIC_EXACT = {"/", "/usar", "/api/voices", "/manifest.webmanifest", "/sw.js", "/favicon.svg", "/favicon.ico"}
PUBLIC_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/static")

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".srt", ".vtt"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
MEDIA_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}


# ---------------------------------------------------------------------------
# Erros no formato {"error": {...}} (mesmo padrão do supertonic serve)
# ---------------------------------------------------------------------------
class UsarError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "invalid_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _err(status: int, message: str, code: str, type_: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": type_, "code": code}},
    )


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------
class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if path in PUBLIC_EXACT or any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
            return await call_next(request)

        provided = request.headers.get("x-api-key") or ""
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()

        if not provided or not secrets.compare_digest(provided, self.api_key):
            return _err(
                401,
                "Chave inválida. Envie o cabeçalho X-API-Key ou Authorization: Bearer <chave>.",
                "invalid_api_key",
                "authentication_error",
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# Extração de texto
# ---------------------------------------------------------------------------
def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise UsarError("Leitura de PDF indisponível no servidor (pypdf).", 501, "pdf_unavailable") from e
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # pragma: no cover - PDFs quebrados
            continue
    text = "\n\n".join(pages)
    if not text.strip():
        raise UsarError(
            "Esse PDF parece ser só imagem (escaneado). Não consegui extrair texto.",
            422,
            "pdf_no_text",
        )
    return text


def _extract_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError as e:  # pragma: no cover
        raise UsarError("Leitura de Word indisponível no servidor (python-docx).", 501, "docx_unavailable") from e
    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_plain(data: bytes, ext: str) -> str:
    text = data.decode("utf-8", errors="replace")
    if ext in {".html", ".htm"}:
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    if ext in {".srt", ".vtt"}:
        text = re.sub(r"^\d+\s*$", "", text, flags=re.M)
        text = re.sub(r"\d{2}:\d{2}:\d{2}[.,]\d{3} --> .*$", "", text, flags=re.M)
        text = text.replace("WEBVTT", "")
    return text


def _extract_image(data: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise UsarError(
            "OCR de imagem não está instalado neste servidor. Envie um PDF com texto ou cole o texto.",
            501,
            "ocr_unavailable",
        ) from e
    if not shutil.which("tesseract"):
        raise UsarError("Tesseract não encontrado no servidor.", 501, "ocr_unavailable")
    img = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(img, lang=os.environ.get("TESSERACT_LANG", "por+eng"))


_whisper_model = None
_whisper_lock = asyncio.Lock()


def _load_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise UsarError(
                "Transcrição de áudio/vídeo não está habilitada neste servidor "
                "(instale requirements-transcribe.txt).",
                501,
                "transcription_unavailable",
            ) from e
        compute = "int8" if WHISPER_DEVICE == "cpu" else "float16"
        logger.info("Carregando faster-whisper %s (%s)…", WHISPER_MODEL, WHISPER_DEVICE)
        _whisper_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=compute)
    return _whisper_model


def _transcribe_path(path: str) -> str:
    model = _load_whisper()
    segments, _info = model.transcribe(path, vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def _download_media(url: str, workdir: str) -> str:
    """Baixa áudio de um link (YouTube etc. via yt-dlp, ou MP4 direto)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UsarError("Link inválido. Use http(s).", 400, "bad_url")

    ytdlp = shutil.which("yt-dlp")
    if ytdlp is None:
        try:
            import yt_dlp  # noqa: F401

            ytdlp_cmd = ["python", "-m", "yt_dlp"]
        except ImportError:
            ytdlp_cmd = None
    else:
        ytdlp_cmd = [ytdlp]

    out_tpl = os.path.join(workdir, "media.%(ext)s")
    if ytdlp_cmd:
        cmd = ytdlp_cmd + [
            "-f", "bestaudio/best", "--no-playlist", "--quiet", "--no-warnings",
            "--max-filesize", f"{MAX_UPLOAD_MB * 4}m", "-o", out_tpl, url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            msg = (proc.stderr or "").strip().splitlines()[-1:] or ["falha desconhecida"]
            raise UsarError(
                "Não consegui baixar o vídeo (" + msg[0][:160] + "). "
                "Baixe o arquivo e envie na aba Arquivo.",
                502,
                "download_failed",
            )
    else:
        import urllib.request

        dest = os.path.join(workdir, "media.bin")
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f, length=1 << 20)

    files = [p for p in Path(workdir).iterdir() if p.name.startswith("media.")]
    if not files:
        raise UsarError("Download vazio.", 502, "download_failed")
    return str(files[0])


def _extract_from_upload(filename: str, data: bytes) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in PDF_EXT:
        return _extract_pdf(data)
    if ext in DOCX_EXT:
        return _extract_docx(data)
    if ext in TEXT_EXT or ext == "":
        return _extract_plain(data, ext)
    if ext in IMAGE_EXT:
        return _extract_image(data)
    if ext in MEDIA_EXT:
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "media" + ext)
            with open(p, "wb") as f:
                f.write(data)
            return _transcribe_path(p)
    raise UsarError(f"Tipo de arquivo não suportado: {ext or 'sem extensão'}.", 415, "unsupported_type")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def build_app() -> FastAPI:
    app = create_app(model=MODEL)
    state = app.state.server_state

    @app.get("/", include_in_schema=False)
    async def root():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", include_in_schema=False)
    async def health():
        ready = bool(getattr(state, "is_ready", False) and state.tts is not None)
        return {"status": "ok" if ready else "loading", "model": MODEL, "service": "supertonic"}

    @app.get("/api/voices", include_in_schema=False)
    async def voices():
        names = list(state.tts.voice_style_names) if state.tts else []
        return {"voices": names, "custom": sorted(state.custom_styles.keys()), "default_lang": DEFAULT_LANG}

    @app.post("/usar", include_in_schema=False)
    async def usar(
        request: Request,
        text: Optional[str] = Form(None),
        url: Optional[str] = Form(None),
        voice: str = Form("F1"),
        lang: Optional[str] = Form(None),
        speed: Optional[float] = Form(None),
        response_format: str = Form("wav"),
        file: Optional[UploadFile] = File(None),
    ):
        """Rota da interface.

        * ``text``  → devolve áudio (``audio/*``) com o texto em ``X-Texto`` (URL-encoded).
        * ``file``  → extrai/transcreve e devolve áudio + ``X-Texto``.
        * ``url``   → baixa e transcreve; devolve JSON ``{"text": ...}`` (a UI pede o
          áudio numa segunda chamada para poder mostrar a transcrição antes).
        """
        if state.tts is None:
            return _err(503, "Modelo ainda carregando. Tente em alguns segundos.", "model_loading", "server_error")

        fmt = (response_format or "wav").lower()
        if fmt not in SUPPORTED_FORMATS:
            return _err(400, f"Formato inválido. Use: {', '.join(SUPPORTED_FORMATS)}.", "unsupported_response_format")

        try:
            content = None
            if url and url.strip():
                with tempfile.TemporaryDirectory() as tmp:
                    media = await asyncio.to_thread(_download_media, url.strip(), tmp)
                    async with _whisper_lock:
                        content = await asyncio.to_thread(_transcribe_path, media)
                content = _clean_text(content)
                if not content:
                    raise UsarError("A transcrição veio vazia.", 422, "empty_transcript")
                return JSONResponse({"text": content[:MAX_TEXT_CHARS], "truncated": len(content) > MAX_TEXT_CHARS})

            if file is not None and file.filename:
                data = await file.read()
                if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
                    raise UsarError(f"Arquivo maior que {MAX_UPLOAD_MB} MB.", 413, "file_too_large")
                if not data:
                    raise UsarError("Arquivo vazio.", 400, "empty_file")
                ext = Path(file.filename).suffix.lower()
                if ext in MEDIA_EXT:
                    async with _whisper_lock:
                        content = await asyncio.to_thread(_extract_from_upload, file.filename, data)
                else:
                    content = await asyncio.to_thread(_extract_from_upload, file.filename, data)
            elif text and text.strip():
                content = text
            else:
                raise UsarError("Envie um texto, um arquivo ou um link.", 400, "missing_input")

            content = _clean_text(content or "")
            if not content:
                raise UsarError("Não encontrei texto para ler.", 422, "empty_text")
            truncated = len(content) > MAX_TEXT_CHARS
            content = content[:MAX_TEXT_CHARS]

            try:
                wav, duration = await asyncio.to_thread(
                    _do_synthesize,
                    state,
                    text=content,
                    voice=voice or "F1",
                    lang=(lang or DEFAULT_LANG) or None,
                    speed=speed,
                    steps=None,
                    max_chunk_length=None,
                    silence_duration=None,
                )
            except UnknownVoice as e:
                raise UsarError(f"Voz desconhecida: {e}", 400, "unknown_voice") from e

            body = encode_audio(wav, state.tts.sample_rate, fmt)
            headers = {
                "X-Texto": urllib.parse.quote(content[:8000]),
                "X-Duration-Seconds": f"{duration:.2f}",
                "X-Truncated": "1" if truncated else "0",
                "Cache-Control": "no-store",
            }
            return Response(content=body, media_type=format_to_mime(fmt), headers=headers)

        except UsarError as e:
            return _err(e.status, e.message, e.code)
        except subprocess.TimeoutExpired:
            return _err(504, "Demorou demais para baixar o vídeo.", "download_timeout", "server_error")
        except Exception as e:  # pragma: no cover
            logger.exception("Falha em /usar")
            return _err(500, f"Erro inesperado: {type(e).__name__}.", "internal_error", "server_error")

    # PWA: manifest e service worker precisam ficar na raiz.
    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    async def sw():
        return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    api_key = (os.environ.get("API_KEY") or "").strip()
    if api_key:
        app.add_middleware(ApiKeyMiddleware, api_key=api_key)
    else:
        logger.warning("API_KEY não definida — /v1/* está aberto.")
    return app


app = build_app()


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
