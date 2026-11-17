"""Supabase persistence adapter for SuperTonic (Single-Tenant / Private Instance).

Provides persistent cloud backup for audio files, job states, documents, and shares.
Activates automatically when SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set.
Requires an explicit canonical SUPABASE_OWNER_ID. Unconfigured means local-only.
This server-only adapter does NOT authenticate callers; routes must do so.
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
SUPABASE_OWNER_ID = os.environ.get("SUPABASE_OWNER_ID", "").strip()

_client = None


def is_enabled() -> bool:
    try:
        owner = str(uuid.UUID(SUPABASE_OWNER_ID))
    except (ValueError, TypeError, AttributeError):
        return False
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and owner == SUPABASE_OWNER_ID)


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


def _audio_path(job_uuid: str, path: Any) -> str:
    """Validate database storage references before using the privileged client."""
    canonical = str(uuid.UUID(job_uuid))
    prefix = f"{SUPABASE_OWNER_ID}/{canonical}/"
    if (not isinstance(path, str) or not path.startswith(prefix)
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path or "%" in path):
        raise ValueError("Invalid audio storage ownership")
    return path


def _signed_url(client, job_uuid: str, path: str, expires_in: int) -> Optional[str]:
    if isinstance(expires_in, bool) or not isinstance(expires_in, int) or not 1 <= expires_in <= 7200:
        raise ValueError("Invalid signed URL lifetime")
    path = _audio_path(job_uuid, path)
    result = client.storage.from_("supertonic-audio").create_signed_url(path, expires_in)
    return result.get("signedURL") or result.get("signedUrl")


def persist_completed_job_sync(job) -> bool:
    """Faz upload do áudio final e persiste metadados no Supabase (executado em background)."""
    client = get_client()
    if not client or not getattr(job, "final", None):
        return False
    final_path = Path(job.final)
    if not final_path.is_file():
        return False

    try:
        job_uuid = job_uuid_for(job.id)
        doc_uuid = doc_uuid_for(job.id)
        fmt = getattr(job, "format", "wav")
        # Renderer owns the supported-format list; only enforce safe path syntax here.
        if not isinstance(fmt, str) or not (1 <= len(fmt) <= 10) or not fmt.isascii() or not fmt.isalnum():
            return False
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
        config = {
            "voice": voice, "format": fmt,
            "speed": getattr(job, "speed", None), "pause": getattr(job, "pause", 0.0),
            "lang": getattr(job, "lang", None),
            "mode": getattr(job, "mode", "normal"),
            "podcast_voices": getattr(job, "podcast_voices", []),
            "duration": getattr(job, "duration", 0.0),
            "local_job_id": job.id,
        }
        plan = getattr(job, "chunks", []) or ["texto"]
        # Include all persisted rendering options and the exact chunk plan.
        key_options = {k: v for k, v in config.items() if k not in {"duration", "local_job_id"}}
        cache_k = hashlib.sha256(json.dumps(
            [SUPABASE_OWNER_ID, text, "supertonic-tts", key_options, plan],
            sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

        client.table("jobs").upsert({
            "id": job_uuid,
            "owner_id": SUPABASE_OWNER_ID,
            "document_id": doc_uuid,
            "model": "supertonic-tts",
            "config": config,
            "plan": plan,
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


async def persist_completed_job(job) -> bool:
    """Invoca persistência de forma assíncrona para não bloquear o event loop."""
    if not is_enabled():
        return False
    try:
        return await asyncio.to_thread(persist_completed_job_sync, job)
    except Exception as e:
        logger.warning("Falha assíncrona ao persistir job %s no Supabase: %s", getattr(job, "id", "?"), e)
        return False


def get_job_meta(local_job_id: str) -> Optional[Dict[str, Any]]:
    """Recupera metadados de job concluído do Supabase caso o servidor local tenha reiniciado."""
    client = get_client()
    if not client:
        return None
    try:
        job_uuid = job_uuid_for(local_job_id)
        res = client.table("jobs").select("*, documentos(title, text)").eq("id", job_uuid).eq("owner_id", SUPABASE_OWNER_ID).eq("status", "done").limit(1).execute()
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
            "duration": config.get("duration", 0.0),
            "text": doc.get("text", ""),
            "title": doc.get("title", ""),
            "audio_url": f"/api/jobs/{local_job_id}/audio",
        }
    except Exception as e:
        logger.warning("Erro ao buscar job %s no Supabase: %s", local_job_id, e)
        return None


def get_audio_signed_url(local_job_id: str, fmt: str, expires_in: int = 3600) -> Optional[str]:
    """Gera link assinado do Supabase Storage para reprodução ou download direto."""
    # fmt is kept for compatibility; persisted metadata is authoritative after restart.
    return get_audio_url_by_uuid(job_uuid_for(local_job_id), expires_in)



def list_saved_documents() -> list[dict]:
    """Lista todos os documentos salvos no Supabase para a biblioteca."""
    client = get_client()
    if not client:
        return []
    try:
        res = (
            client.table("jobs")
            .select("id, status, created_at, config, audio_path, documentos(id, title, text)")
            .eq("owner_id", SUPABASE_OWNER_ID)
            .eq("status", "done")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        items = []
        for r in res.data:
            doc = r.get("documentos") or {}
            cfg = r.get("config") or {}
            job_uuid = r["id"]
            fmt = cfg.get("format", "mp3")
            text = doc.get("text", "") or ""
            items.append({
                "job_uuid": job_uuid,
                "title": doc.get("title") or "Documento sem título",
                "preview": (text[:160] + "...") if len(text) > 160 else text,
                "created_at": r["created_at"],
                "format": fmt,
                "voice": cfg.get("voice", "F1"),
                "status": r.get("status", "done"),
                "has_audio": bool(r.get("audio_path")),
                "audio_url": f"/api/documents/{job_uuid}/audio",
            })
        return items
    except Exception as e:
        logger.warning("Erro ao listar documentos no Supabase: %s", e)
        return []


def delete_saved_document(job_uuid: str) -> bool:
    """Remove an owned job and audio. Retain source document to avoid cascade loss.

    Documents can be referenced by multiple jobs. Safe source cleanup requires a
    transactional database operation; do not cascade-delete it through REST.
    """
    client = get_client()
    if not client:
        return False
    try:
        job_res = (
            client.table("jobs")
            .select("audio_path, document_id")
            .eq("id", job_uuid)
            .eq("owner_id", SUPABASE_OWNER_ID)
            .limit(1)
            .execute()
        )
        if job_res.data:
            audio_path = job_res.data[0].get("audio_path")
            if audio_path:
                _audio_path(job_uuid, audio_path)
            # Delete metadata first: an object-removal failure must not leave a
            # discoverable "done" row pointing to a missing audio object.
            client.table("jobs").delete().eq("id", job_uuid).eq("owner_id", SUPABASE_OWNER_ID).execute()
            if audio_path:
                client.storage.from_("supertonic-audio").remove([audio_path])
        return True
    except Exception as e:
        logger.warning("Erro ao deletar documento %s: %s", job_uuid, e)
        return False


def get_audio_url_by_uuid(job_uuid: str, expires_in: int = 7200) -> Optional[str]:
    """Retorna URL assinada do Supabase Storage diretamente pelo UUID do job."""
    client = get_client()
    if not client:
        return None
    try:
        job = (
            client.table("jobs")
            .select("audio_path")
            .eq("status", "done")
            .eq("id", job_uuid)
            .eq("owner_id", SUPABASE_OWNER_ID)
            .limit(1)
            .execute()
        )
        if job.data and job.data[0].get("audio_path"):
            path = job.data[0]["audio_path"]
            return _signed_url(client, job_uuid, path, expires_in)
    except Exception as e:
        logger.warning("Erro ao gerar URL assinada para %s: %s", job_uuid, e)
    return None
