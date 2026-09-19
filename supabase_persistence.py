"""Supabase persistence adapter for SuperTonic (Single-Tenant / Private Instance).

Provides persistent cloud backup for audio files, job states, documents, and shares.
Activates automatically when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set.
Falls back seamlessly to local disk if unconfigured.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("supertonic.supabase")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_OWNER_ID = os.environ.get("SUPABASE_OWNER_ID", "af31d1a3-7702-441b-bb7e-6650600e67e0").strip()

_client = None


def is_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def get_client():
    global _client
    if not is_enabled():
        return None
    if _client is None:
        try:
            from supabase import create_client
            from supabase.lib.client_options import SyncClientOptions

            opts = SyncClientOptions(
                auto_refresh_token=False,
                persist_session=False,
                postgrest_client_timeout=15,
                storage_client_timeout=30,
            )
            _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, options=opts)
        except Exception as e:
            logger.error("Falha ao inicializar cliente Supabase: %s", e)
            return None
    return _client


def job_uuid_for(local_job_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"supertonic-job:{local_job_id}"))


def doc_uuid_for(local_job_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"supertonic-doc:{local_job_id}"))


def persist_completed_job_sync(job) -> bool:
    """Faz upload do áudio final e persiste metadados no Supabase (executado em background)."""
    client = get_client()
    if not client or not getattr(job, "final", None):
        return False
    final_path = Path(job.final)
    if not final_path.exists():
        return False

    try:
        job_uuid = job_uuid_for(job.id)
        doc_uuid = doc_uuid_for(job.id)
        fmt = getattr(job, "format", "wav")
        audio_path = f"{SUPABASE_OWNER_ID}/{job_uuid}/output.{fmt}"

        # 1. Documento
        title = "Documento"
        inp = getattr(job, "input", {}) or {}
        if isinstance(inp, dict) and inp.get("file"):
            title = str(inp["file"][0])[:200]

        client.table("documentos").upsert({
            "id": doc_uuid,
            "owner_id": SUPABASE_OWNER_ID,
            "title": title,
            "text": getattr(job, "text", "") or "",
        }).execute()

        # 2. Upload do áudio para o bucket privado
        mime_map = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "m4b": "audio/mp4",
        }
        mime = mime_map.get(fmt, "audio/octet-stream")

        with open(final_path, "rb") as f:
            audio_bytes = f.read()

        client.storage.from_("supertonic-audio").upload(
            path=audio_path,
            file=audio_bytes,
            file_options={"content-type": mime, "upsert": "true"},
        )

        # 3. Registro do Job
        text = getattr(job, "text", "") or ""
        voice = getattr(job, "voice", "F1")
        cache_k = hashlib.sha256(f"{SUPABASE_OWNER_ID}:{text}:{voice}:{fmt}".encode()).hexdigest()

        client.table("jobs").upsert({
            "id": job_uuid,
            "owner_id": SUPABASE_OWNER_ID,
            "document_id": doc_uuid,
            "model": "supertonic-tts",
            "config": {
                "voice": voice,
                "format": fmt,
                "speed": getattr(job, "speed", 1.0),
                "pause": getattr(job, "pause", 0.0),
            },
            "plan": getattr(job, "chunks", []) or ["texto"],
            "cache_key": cache_k,
            "status": "done",
            "audio_path": audio_path,
            "worker_id": None,
            "claim_token": None,
            "lease_until": None,
        }).execute()

        logger.info("Job %s persistido no Supabase (UUID: %s)", job.id, job_uuid)
        return True
    except Exception as e:
        logger.warning("Erro ao persistir job %s no Supabase: %s", getattr(job, "id", "?"), e)
        return False


async def persist_completed_job(job) -> None:
    """Invoca persistência de forma assíncrona para não bloquear o event loop."""
    if not is_enabled():
        return
    try:
        await asyncio.to_thread(persist_completed_job_sync, job)
    except Exception as e:
        logger.warning("Falha assíncrona ao persistir job %s no Supabase: %s", getattr(job, "id", "?"), e)


def get_job_meta(local_job_id: str) -> Optional[Dict[str, Any]]:
    """Recupera metadados de job concluído do Supabase caso o servidor local tenha reiniciado."""
    client = get_client()
    if not client:
        return None
    try:
        job_uuid = job_uuid_for(local_job_id)
        res = client.table("jobs").select("*, documentos(title, text)").eq("id", job_uuid).limit(1).execute()
        if not res.data:
            return None
        row = res.data[0]
        doc = row.get("documentos") or {}
        config = row.get("config") or {}
        return {
            "id": local_job_id,
            "uuid": job_uuid,
            "status": row.get("status", "done"),
            "stage": "done",
            "percent": 100,
            "message": "Pronto (restaurado do Supabase)",
            "format": config.get("format", "mp3"),
            "voice": config.get("voice", "F1"),
            "chunks": row.get("plan") or [],
            "chunks_ready": len(row.get("plan") or []),
            "duration": 0.0,
            "text": doc.get("text", ""),
            "title": doc.get("title", ""),
            "audio_url": f"/api/jobs/{local_job_id}/audio",
        }
    except Exception as e:
        logger.warning("Erro ao buscar job %s no Supabase: %s", local_job_id, e)
        return None


def get_audio_signed_url(local_job_id: str, fmt: str, expires_in: int = 3600) -> Optional[str]:
    """Gera link assinado do Supabase Storage para reprodução ou download direto."""
    client = get_client()
    if not client:
        return None
    try:
        job_uuid = job_uuid_for(local_job_id)
        audio_path = f"{SUPABASE_OWNER_ID}/{job_uuid}/output.{fmt}"
        res = client.storage.from_("supertonic-audio").create_signed_url(audio_path, expires_in)
        return res.get("signedURL") or res.get("signedUrl")
    except Exception as e:
        logger.warning("Erro ao gerar signed URL para job %s: %s", local_job_id, e)
        return None
