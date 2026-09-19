"""Optional synchronous Supabase persistence adapter (not wired into server.py).

Every method performs blocking I/O: call via asyncio.to_thread in async routes.
Inject separate Auth and service-role clients; never set a user session on admin.
The admin client and worker methods are server-only capabilities.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

AUDIO_BUCKET = "supertonic-audio"
DOCUMENT_BUCKET = "supertonic-documentos"
MAX_SIGNED_SECONDS = 60
MAX_SHARE_SECONDS = 7 * 24 * 3600


class AuthenticationError(PermissionError):
    pass


class NotFound(LookupError):
    pass


def full_uuid(value: str) -> str:
    """Reject the application's legacy 12-character IDs and noncanonical UUIDs."""
    parsed = str(UUID(str(value)))
    if str(value) != parsed:
        raise ValueError("Expected a complete canonical UUID")
    return parsed


def cache_key(owner_id: str, text: str, model: str, config: dict) -> str:
    """Include model revision, normalization revision, voice and every audio option."""
    payload = [full_uuid(owner_id), text, model, config]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def token_hash(token: str) -> str:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise NotFound("Share unavailable")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _date(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result


class SupabaseBackend:
    def __init__(self, auth_client: Any, admin_client: Any,
                 clock: Callable[[], datetime] = _now):
        self.auth = auth_client
        self.admin = admin_client
        self.clock = clock

    def verify_user(self, jwt: str) -> str:
        """Network verification with Supabase Auth; never trust decoded JWT claims."""
        if not isinstance(jwt, str) or not jwt.strip():
            raise AuthenticationError("Missing bearer token")
        try:
            response = self.auth.auth.get_user(jwt)
            if response.user is None:
                raise ValueError("Missing user")
            return full_uuid(str(response.user.id))
        except Exception as exc:
            raise AuthenticationError("Invalid or unavailable authentication") from exc

    @staticmethod
    def _one(query: Any) -> dict:
        rows = query.limit(1).execute().data
        if not rows:
            raise NotFound("Resource unavailable")
        return rows[0]

    def _owned_job(self, owner: str, job_id: str) -> dict:
        return self._one(self.admin.table("jobs").select("*")
                         .eq("id", full_uuid(job_id)).eq("owner_id", owner))

    def create_document(self, jwt: str, title: str, text: str) -> dict:
        owner = self.verify_user(jwt)
        row = {"id": str(uuid4()), "owner_id": owner, "title": title[:200], "text": text}
        return self.admin.table("documentos").insert(row).execute().data[0]

    def create_job(self, jwt: str, document_id: str, model: str,
                   config: dict, plan: list[str]) -> dict:
        """Plan is the final normalized split; persist before enqueueing a worker."""
        owner = self.verify_user(jwt)
        doc = self._one(self.admin.table("documentos").select("id,text")
                        .eq("id", full_uuid(document_id)).eq("owner_id", owner))
        if not model or not plan or any(not isinstance(t, str) or not t for t in plan):
            raise ValueError("Model and nonempty chunk plan required")
        # Hash final plan as well as source to invalidate split/normalization changes.
        key = cache_key(owner, doc["text"], model, {"options": config, "plan": plan})
        row = {"id": str(uuid4()), "owner_id": owner, "document_id": doc["id"],
               "model": model, "config": config, "plan": plan, "cache_key": key}
        return self.admin.table("jobs").insert(row).execute().data[0]

    def get_job(self, jwt: str, job_id: str) -> dict:
        return self._owned_job(self.verify_user(jwt), job_id)

    def cached_job(self, jwt: str, key: str) -> dict | None:
        owner = self.verify_user(jwt)
        rows = (self.admin.table("jobs").select("*").eq("owner_id", owner)
                .eq("cache_key", key).eq("status", "done").order("created_at", desc=True)
                .limit(1).execute().data)
        return rows[0] if rows else None

    def list_chunks(self, jwt: str, job_id: str) -> list[dict]:
        owner = self.verify_user(jwt)
        self._owned_job(owner, job_id)
        return (self.admin.table("chunks").select("*").eq("owner_id", owner)
                .eq("job_id", job_id).order("chunk_index").execute().data)

    def claim_job(self, worker_id: str, lease_seconds: int = 120) -> dict | None:
        """SERVER WORKER ONLY. Atomic SKIP LOCKED claim or expired-lease takeover."""
        rows = self.admin.rpc("st_claim_job", {"p_worker": full_uuid(worker_id),
                             "p_seconds": lease_seconds}).execute().data
        return rows[0] if rows else None

    def worker_chunks(self, job: dict) -> list[dict]:
        """SERVER WORKER ONLY. Committed checkpoints survive process/lease loss."""
        return (self.admin.table("chunks").select("*")
                .eq("owner_id", full_uuid(job["owner_id"]))
                .eq("job_id", full_uuid(job["id"])).order("chunk_index").execute().data)

    def download_chunk(self, job: dict, chunk: dict) -> bytes:
        """SERVER WORKER ONLY. Recover persisted audio for final concatenation."""
        prefix = f"{full_uuid(job['owner_id'])}/{full_uuid(job['id'])}/"
        path = chunk["audio_path"]
        if not path.startswith(prefix) or ".." in path.split("/"):
            raise PermissionError("Invalid storage ownership")
        return self.admin.storage.from_(AUDIO_BUCKET).download(path)

    def heartbeat(self, job_id: str, claim_token: str, lease_seconds: int = 120) -> bool:
        return bool(self.admin.rpc("st_heartbeat", {"p_job": full_uuid(job_id),
                    "p_token": full_uuid(claim_token), "p_seconds": lease_seconds}).execute().data)

    def _upload(self, job: dict, token: str, name: str, audio: bytes, mime: str) -> str:
        # Claim-scoped immutable names prevent stale workers overwriting a successor.
        path = f"{full_uuid(job['owner_id'])}/{full_uuid(job['id'])}/{full_uuid(token)}/{name}"
        self.admin.storage.from_(AUDIO_BUCKET).upload(
            path, audio, {"content-type": mime, "upsert": "false"})
        return path

    def save_chunk(self, job: dict, claim_token: str, index: int, audio: bytes) -> dict:
        """SERVER WORKER ONLY. Use claim result, not request-supplied job metadata."""
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ValueError("Invalid chunk index")
        path = self._upload(job, claim_token, f"chunk-{index}-{uuid4()}.wav", audio, "audio/wav")
        return self.admin.rpc("st_checkpoint", {"p_job": full_uuid(job["id"]),
            "p_token": full_uuid(claim_token), "p_index": index, "p_path": path}).execute().data

    def finish_job(self, job: dict, claim_token: str, audio: bytes,
                   extension: str = "mp3") -> dict:
        mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac"}
        if extension not in mime:
            raise ValueError("Unsupported audio format")
        path = self._upload(job, claim_token, f"final-{uuid4()}.{extension}", audio, mime[extension])
        return self.admin.rpc("st_finish", {"p_job": full_uuid(job["id"]),
            "p_token": full_uuid(claim_token), "p_path": path}).execute().data

    def fail_job(self, job_id: str, claim_token: str) -> bool:
        """Terminal failure. Error details belong in redacted server logs."""
        return bool(self.admin.rpc("st_fail", {"p_job": full_uuid(job_id),
                    "p_token": full_uuid(claim_token)}).execute().data)

    def _signed(self, job: dict, path: str, seconds: int,
                not_after: datetime | None = None) -> str:
        prefix = f"{full_uuid(job['owner_id'])}/{full_uuid(job['id'])}/"
        if not path.startswith(prefix) or ".." in path.split("/"):
            raise PermissionError("Invalid storage ownership")
        if not 1 <= seconds <= MAX_SIGNED_SECONDS:
            raise ValueError("Invalid URL lifetime")
        result = self.admin.storage.from_(AUDIO_BUCKET).create_signed_url(path, seconds)
        url = result["signedURL"]
        if not_after is not None:
            # Inspect ONLY the trusted Storage response, never a user's Auth JWT.
            # Fail closed if server clock skew/network delay exceeds our margin.
            from urllib.parse import parse_qs, urlsplit
            try:
                token = parse_qs(urlsplit(url).query)["token"][0]
                payload = token.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                expiry = claims["exp"]
                if (not isinstance(expiry, (int, float)) or isinstance(expiry, bool)
                        or not math.isfinite(expiry) or expiry > not_after.timestamp()):
                    raise ValueError("Storage expiry exceeds share expiry")
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise NotFound("Unable to bound share URL expiration") from exc
        return url

    def audio_url(self, jwt: str, job_id: str, seconds: int = 60) -> str:
        job = self._owned_job(self.verify_user(jwt), job_id)
        if job["status"] != "done" or not job.get("audio_path"):
            raise NotFound("Audio unavailable")
        return self._signed(job, job["audio_path"], min(MAX_SIGNED_SECONDS, seconds))

    def chunk_url(self, jwt: str, job_id: str, index: int, seconds: int = 60) -> str:
        owner = self.verify_user(jwt)
        job = self._owned_job(owner, job_id)
        chunk = self._one(self.admin.table("chunks").select("audio_path")
                          .eq("owner_id", owner).eq("job_id", job_id).eq("chunk_index", index))
        return self._signed(job, chunk["audio_path"], min(MAX_SIGNED_SECONDS, seconds))

    def create_share(self, jwt: str, job_id: str, lifetime_seconds: int = 3600) -> str:
        owner = self.verify_user(jwt)
        job = self._owned_job(owner, job_id)
        if job["status"] != "done":
            raise NotFound("Audio unavailable")
        if not 1 <= lifetime_seconds <= MAX_SHARE_SECONDS:
            raise ValueError("Share lifetime out of range")
        token = secrets.token_urlsafe(32)
        self.admin.table("shares").insert({"owner_id": owner, "job_id": job_id,
            "token_hash": token_hash(token),
            "expires_at": (self.clock() + timedelta(seconds=lifetime_seconds)).isoformat()}).execute()
        return token  # returned only once; never store/log the raw token

    def revoke_share(self, jwt: str, token: str) -> None:
        owner = self.verify_user(jwt)
        self.admin.table("shares").update({"revoked_at": self.clock().isoformat()}).eq(
            "owner_id", owner).eq("token_hash", token_hash(token)).execute()

    def resolve_share(self, token: str, seconds: int = 60) -> str:
        """Backend-only bearer-capability resolution; no public SELECT or RPC."""
        digest = token_hash(token)
        share = self._one(self.admin.table("shares").select("*").eq("token_hash", digest))
        if share.get("revoked_at"):
            raise NotFound("Share unavailable")
        job = self._owned_job(share["owner_id"], share["job_id"])
        # Reserve 2s for latency/clock skew; calculate after the DB requests.
        remaining = math.floor((_date(share["expires_at"]) - self.clock()).total_seconds()) - 2
        ttl = min(MAX_SIGNED_SECONDS, seconds, remaining)
        if ttl < 1 or job["status"] != "done" or not job.get("audio_path"):
            raise NotFound("Share unavailable")
        return self._signed(job, job["audio_path"], ttl, not_after=_date(share["expires_at"]))


def create_backend(url: str, publishable_key: str, service_role_key: str) -> SupabaseBackend:
    """Optional dependency imported lazily; install supabase separately to enable."""
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
    def options():
        return SyncClientOptions(auto_refresh_token=False, persist_session=False,
                                 postgrest_client_timeout=20, storage_client_timeout=20)
    return SupabaseBackend(create_client(url, publishable_key, options=options()),
                           create_client(url, service_role_key, options=options()))
