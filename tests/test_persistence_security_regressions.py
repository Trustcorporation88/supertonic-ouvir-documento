"""Offline regression tests. No SDK, credentials, or external writes required."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import asyncio
import pytest
import supabase_persistence as p

OWNER = '11111111-1111-4111-8111-111111111111'
JOB = p.job_uuid_for('local123')

@pytest.fixture
def client(monkeypatch):
    c = MagicMock()
    q = c.table.return_value
    for name in ('select', 'eq', 'limit', 'order', 'delete', 'upsert'):
        getattr(q, name).return_value = q
    q.execute.return_value.data = []
    monkeypatch.setattr(p, 'get_client', lambda: c)
    monkeypatch.setattr(p, 'SUPABASE_OWNER_ID', OWNER)
    return c

def rows(c, values):
    c.table.return_value.execute.return_value.data = values

def filters(c):
    return [tuple(call.args) for call in c.table.return_value.eq.call_args_list]

def test_enabled_requires_explicit_canonical_owner(monkeypatch):
    monkeypatch.setattr(p, 'SUPABASE_URL', 'https://example.invalid')
    monkeypatch.setattr(p, 'SUPABASE_SERVICE_ROLE_KEY', 'dummy-offline')
    for value in ('', 'bad', OWNER.replace('-', '')):
        monkeypatch.setattr(p, 'SUPABASE_OWNER_ID', value)
        assert not p.is_enabled()
    monkeypatch.setattr(p, 'SUPABASE_OWNER_ID', OWNER)
    assert p.is_enabled()

def test_restored_wav_uses_database_path_not_mp3_guess(client):
    path = f'{OWNER}/{JOB}/output.wav'
    rows(client, [{'audio_path': path}])
    client.storage.from_.return_value.create_signed_url.return_value = {'signedURL': 'https://example.invalid/offline'}
    assert p.get_audio_signed_url('local123', 'mp3') == 'https://example.invalid/offline'
    client.storage.from_.return_value.create_signed_url.assert_called_once_with(path, 3600)
    assert ('owner_id', OWNER) in filters(client)
    assert ('status', 'done') in filters(client)

@pytest.mark.parametrize('path', [f'other/{JOB}/output.wav', f'{OWNER}/{JOB}/../secret', f'{OWNER}/{JOB}/%2e%2e/secret', f'{OWNER}/{JOB}/a\\secret'])
def test_signing_rejects_invalid_storage_ownership(client, path):
    rows(client, [{'audio_path': path}])
    assert p.get_audio_url_by_uuid(JOB) is None
    client.storage.from_.assert_not_called()

def test_metadata_scopes_owner_and_done_and_restores_duration(client):
    rows(client, [{'status': 'done', 'config': {'duration': 3.5}, 'documentos': {'text': 'hello'}, 'plan': ['hello']}])
    assert p.get_job_meta('local123')['duration'] == 3.5
    assert ('owner_id', OWNER) in filters(client)
    assert ('status', 'done') in filters(client)

def test_delete_never_cascades_shared_document(client):
    rows(client, [{'audio_path': f'{OWNER}/{JOB}/output.wav', 'document_id': 'shared'}])
    assert p.delete_saved_document(JOB)
    assert all(call.args == ('jobs',) for call in client.table.call_args_list)
    assert filters(client).count(('owner_id', OWNER)) == 2

def test_invalid_path_prevents_delete(client):
    rows(client, [{'audio_path': 'another-owner/file.wav'}])
    assert not p.delete_saved_document(JOB)
    client.table.return_value.delete.assert_not_called()

def test_failed_database_delete_does_not_remove_audio(client):
    q = client.table.return_value
    q.execute.side_effect = [SimpleNamespace(data=[{'audio_path': f'{OWNER}/{JOB}/output.wav'}]), RuntimeError('offline simulated DB failure')]
    assert not p.delete_saved_document(JOB)
    client.storage.from_.assert_not_called()

def test_persist_preserves_metadata_and_varies_cache_with_speed(client, tmp_path):
    audio = tmp_path / 'output.wav'
    audio.write_bytes(b'offline-fixture')
    job = SimpleNamespace(id='local123', final=str(audio), format='wav', input={'file': ('title.txt', 'unused')}, text='hello', voice='F1', speed=1.0, lang='pt', chunks=['hello'], duration=3.5)
    assert p.persist_completed_job_sync(job)
    payload1 = client.table.return_value.upsert.call_args.args[0]
    job.speed = 2.0
    assert p.persist_completed_job_sync(job)
    payload2 = client.table.return_value.upsert.call_args.args[0]
    assert payload1['cache_key'] != payload2['cache_key']
    assert payload1['config']['duration'] == 3.5
    assert payload1['config']['local_job_id'] == 'local123'

def test_async_reports_persistence_failure(monkeypatch):
    monkeypatch.setattr(p, 'is_enabled', lambda: True)
    monkeypatch.setattr(p, 'persist_completed_job_sync', lambda job: False)
    assert asyncio.run(p.persist_completed_job(SimpleNamespace(id='local123'))) is False
