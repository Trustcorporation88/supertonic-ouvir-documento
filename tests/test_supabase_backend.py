from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from supabase_backend import (AuthenticationError, NotFound, SupabaseBackend,
                              cache_key, full_uuid, token_hash)

OWNER = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
OTHER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
JOB = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
CLAIM = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
NOW = datetime(2026, 9, 19, 22, tzinfo=timezone.utc)
PATH = f'{OWNER}/{JOB}/{CLAIM}/audio.mp3'
TOKEN = 'A' * 43


def query(data):
    q = MagicMock()
    for method in ('select', 'eq', 'limit', 'order', 'insert', 'update'):
        getattr(q, method).return_value = q
    q.execute.return_value = SimpleNamespace(data=data)
    return q


@pytest.fixture
def setup():
    auth, admin = MagicMock(), MagicMock()
    auth.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id=OWNER))
    backend = SupabaseBackend(auth, admin, lambda: NOW)
    admin.storage.from_.return_value.create_signed_url.return_value = {'signedURL': 'https://example.test/signed'}
    return backend, auth, admin


def job(**kwargs):
    return dict(id=JOB, owner_id=OWNER, status='done', audio_path=PATH, **kwargs)


def share(**kwargs):
    result = dict(job_id=JOB, owner_id=OWNER, revoked_at=None,
                  expires_at=(NOW + timedelta(seconds=30)).isoformat())
    result.update(kwargs)
    return result


def test_auth_network_verification(setup):
    b, auth, _ = setup
    assert b.verify_user('jwt') == OWNER
    auth.auth.get_user.assert_called_once_with('jwt')


@pytest.mark.parametrize('value', ['', None, 'bad'])
def test_invalid_auth_denies_before_database(setup, value):
    b, auth, admin = setup
    auth.auth.get_user.side_effect = RuntimeError('Auth error')
    with pytest.raises(AuthenticationError):
        b.get_job(value, JOB)
    admin.table.assert_not_called()


def test_auth_missing_user(setup):
    b, auth, _ = setup
    auth.auth.get_user.return_value = SimpleNamespace(user=None)
    with pytest.raises(AuthenticationError):
        b.verify_user('jwt')


@pytest.mark.parametrize('value', ['123456789012', JOB.replace('-', ''), JOB.upper(), '../job'])
def test_full_uuid_required(value):
    with pytest.raises(ValueError):
        full_uuid(value)


def test_owner_filter_and_not_found(setup):
    b, _, admin = setup
    q = query([])
    admin.table.return_value = q
    with pytest.raises(NotFound):
        b.get_job('jwt', JOB)
    q.eq.assert_any_call('owner_id', OWNER)
    q.eq.assert_any_call('id', JOB)


def test_cache_isolation_and_config_order():
    base = cache_key(OWNER, 'text', 'model@1', {'voice': 'F1', 'speed': 1})
    assert base == cache_key(OWNER, 'text', 'model@1', {'speed': 1, 'voice': 'F1'})
    for owner, text, model, config in [
        (OTHER, 'text', 'model@1', {'voice': 'F1', 'speed': 1}),
        (OWNER, 'other', 'model@1', {'voice': 'F1', 'speed': 1}),
        (OWNER, 'text', 'model@2', {'voice': 'F1', 'speed': 1}),
        (OWNER, 'text', 'model@1', {'voice': 'F1', 'speed': 2}),
    ]:
        assert base != cache_key(owner, text, model, config)
    with pytest.raises(ValueError):
        cache_key(OWNER, 'text', 'm', {'speed': float('nan')})


def test_create_job_persists_plan_and_full_uuid(setup):
    b, _, admin = setup
    doc, jobs = query([{'id': JOB, 'text': 'source'}]), query([{'id': JOB}])
    admin.table.side_effect = [doc, jobs]
    b.create_job('jwt', JOB, 'model@revision', {'normalizer': 1}, ['normalized'])
    inserted = jobs.insert.call_args.args[0]
    assert str(UUID(inserted['id'])) == inserted['id']
    assert inserted['owner_id'] == OWNER
    assert inserted['plan'] == ['normalized']
    assert len(inserted['cache_key']) == 64
    doc.eq.assert_any_call('owner_id', OWNER)


def test_cache_lookup_owner_filter(setup):
    b, _, admin = setup
    q = query([])
    admin.table.return_value = q
    assert b.cached_job('jwt', 'x' * 64) is None
    q.eq.assert_any_call('owner_id', OWNER)
    q.eq.assert_any_call('status', 'done')


def test_share_stores_only_hash(setup):
    b, _, admin = setup
    jobs, shares = query([job()]), query([])
    admin.table.side_effect = [jobs, shares]
    token = b.create_share('jwt', JOB)
    row = shares.insert.call_args.args[0]
    assert row['token_hash'] == token_hash(token)
    assert token not in str(row)
    assert row['owner_id'] == OWNER


@pytest.mark.parametrize('seconds', [0, -1, 604801])
def test_share_ttl_bounds(setup, seconds):
    b, _, admin = setup
    admin.table.return_value = query([job()])
    with pytest.raises(ValueError):
        b.create_share('jwt', JOB, seconds)


def storage_url(expiry):
    import base64
    import json
    payload = base64.urlsafe_b64encode(json.dumps({'exp': expiry}).encode()).decode().rstrip('=')
    return f'https://example.test/signed?token=header.{payload}.signature'


def test_share_ttl_clamped_to_expiration(setup):
    b, _, admin = setup
    admin.table.side_effect = [query([share()]), query([job()])]
    url = storage_url((NOW + timedelta(seconds=28)).timestamp())
    admin.storage.from_.return_value.create_signed_url.return_value = {'signedURL': url}
    assert b.resolve_share(TOKEN, 9999) == url
    admin.storage.from_.return_value.create_signed_url.assert_called_once_with(PATH, 28)


@pytest.mark.parametrize('url', [
    storage_url((NOW + timedelta(seconds=31)).timestamp()),
    'https://example.test/signed?token=invalid',
    'https://example.test/signed',
])
def test_share_rejects_storage_expiry_outside_bound(setup, url):
    b, _, admin = setup
    admin.table.side_effect = [query([share()]), query([job()])]
    admin.storage.from_.return_value.create_signed_url.return_value = {'signedURL': url}
    with pytest.raises(NotFound):
        b.resolve_share(TOKEN)


@pytest.mark.parametrize('changes', [
    {'revoked_at': NOW.isoformat()},
    {'expires_at': NOW.isoformat()},
    {'expires_at': (NOW + timedelta(seconds=2)).isoformat()},
])
def test_share_revoked_or_expired_never_signs(setup, changes):
    b, _, admin = setup
    admin.table.side_effect = [query([share(**changes)]), query([job()])]
    with pytest.raises(NotFound):
        b.resolve_share(TOKEN)
    admin.storage.assert_not_called()
    admin.storage.from_.assert_not_called()


def test_owner_url_short_cap(setup):
    b, _, admin = setup
    admin.table.return_value = query([job()])
    b.audio_url('jwt', JOB, 9999)
    admin.storage.from_.return_value.create_signed_url.assert_called_once_with(PATH, 60)


def test_path_ownership_defense(setup):
    b, _, admin = setup
    wrong = job()
    wrong['audio_path'] = f'{OTHER}/{JOB}/audio.mp3'
    admin.table.return_value = query([wrong])
    with pytest.raises(PermissionError):
        b.audio_url('jwt', JOB)
    admin.storage.from_.assert_not_called()


def test_claim_rpc_and_empty_queue(setup):
    b, _, admin = setup
    admin.rpc.return_value.execute.return_value.data = []
    assert b.claim_job(OWNER) is None
    admin.rpc.assert_called_once_with('st_claim_job', {'p_worker': OWNER, 'p_seconds': 120})


def test_chunk_checkpoint_fenced_and_immutable_upload(setup):
    b, _, admin = setup
    b.save_chunk(job(), CLAIM, 0, b'wav')
    path = admin.storage.from_.return_value.upload.call_args.args[0]
    assert path.startswith(f'{OWNER}/{JOB}/{CLAIM}/chunk-0-')
    assert admin.storage.from_.return_value.upload.call_args.args[2]['upsert'] == 'false'
    admin.rpc.assert_called_once_with('st_checkpoint', {
        'p_job': JOB, 'p_token': CLAIM, 'p_index': 0, 'p_path': path})


def test_checkpoint_lost_lease_propagates(setup):
    b, _, admin = setup
    admin.rpc.return_value.execute.side_effect = RuntimeError('Lost claim')
    with pytest.raises(RuntimeError, match='Lost claim'):
        b.save_chunk(job(), CLAIM, 0, b'wav')


def test_heartbeat_and_failure_fenced(setup):
    b, _, admin = setup
    admin.rpc.return_value.execute.return_value.data = False
    assert b.heartbeat(JOB, CLAIM) is False
    assert b.fail_job(JOB, CLAIM) is False
    admin.rpc.assert_any_call('st_fail', {'p_job': JOB, 'p_token': CLAIM})


def test_worker_resume_owner_filter(setup):
    b, _, admin = setup
    q = query([{'chunk_index': 0, 'audio_path': PATH}])
    admin.table.return_value = q
    assert b.worker_chunks(job())[0]['chunk_index'] == 0
    q.eq.assert_any_call('owner_id', OWNER)
    q.eq.assert_any_call('job_id', JOB)


def test_bad_token_no_database(setup):
    b, _, admin = setup
    with pytest.raises(NotFound):
        b.resolve_share('../bad')
    admin.table.assert_not_called()


def test_revoke_filters_owner(setup):
    b, _, admin = setup
    q = query([])
    admin.table.return_value = q
    b.revoke_share('jwt', TOKEN)
    q.eq.assert_any_call('owner_id', OWNER)
    q.eq.assert_any_call('token_hash', token_hash(TOKEN))


def test_migration_static_security_contract():
    from pathlib import Path
    sql = (Path(__file__).parents[1] / 'supabase/migrations/202609190001_supertonic_backend.sql').read_text()
    assert 'using (true)' not in sql.lower()
    assert 'skip locked' in sql.lower()
    assert "claim_token is distinct from p_token" in sql
    assert 'from public,anon,authenticated' in sql
    for name in ['documentos', 'jobs', 'chunks', 'shares']:
        assert f'alter table public.{name} enable row level security' in sql
    assert "('supertonic-audio','supertonic-audio',false)" in sql
    assert 'grant select on public.documentos, public.jobs, public.chunks to authenticated' in sql


def test_sdk_factory_contract_without_network():
    pytest.importorskip('supabase')
    from supabase_backend import create_backend
    backend = create_backend('http://127.0.0.1:54321', 'sb_publishable_test', 'sb_secret_test')
    assert backend.auth is not backend.admin
    assert backend.auth.options.persist_session is False
    assert backend.admin.options.auto_refresh_token is False
    backend.auth.auth.close()
    backend.admin.auth.close()
