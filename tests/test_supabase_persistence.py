import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import supabase_persistence


def test_supabase_disabled_by_default():
    with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
        assert not supabase_persistence.is_enabled()
        assert supabase_persistence.get_client() is None


def test_uuid_generation_is_canonical_and_deterministic():
    u1 = supabase_persistence.job_uuid_for("job123")
    u2 = supabase_persistence.job_uuid_for("job123")
    u3 = supabase_persistence.job_uuid_for("job456")
    assert u1 == u2
    assert u1 != u3
    assert len(u1) == 36


def test_persist_completed_job_sync_graceful_when_disabled():
    with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
        mock_job = MagicMock()
        mock_job.final = None
        assert not supabase_persistence.persist_completed_job_sync(mock_job)


def test_get_job_meta_returns_none_when_disabled():
    with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
        assert supabase_persistence.get_job_meta("job123") is None


def test_get_audio_signed_url_returns_none_when_disabled():
    with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
        assert supabase_persistence.get_audio_signed_url("job123", "mp3") is None
