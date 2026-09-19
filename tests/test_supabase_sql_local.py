"""Optional integration tests: disposable PostgreSQL, NOT a Supabase project.

Requires pgserver and psycopg2-binary. Auth/storage schemas here are minimal
stubs; these tests do not replace testing Supabase Auth/Storage/PostgREST.
"""
from pathlib import Path
import tempfile

import pytest

pgserver = pytest.importorskip('pgserver')
psycopg2 = pytest.importorskip('psycopg2')

A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
WORKER = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'


@pytest.fixture(scope='module')
def database():
    server = pgserver.get_server(tempfile.mkdtemp(prefix='st-pg-'), cleanup_mode='delete')
    uri = server.get_uri()
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("""
        create role anon nologin;
        create role authenticated nologin;
        create role service_role nologin bypassrls;
        create schema auth;
        create table auth.users(id uuid primary key);
        create function auth.uid() returns uuid language sql stable as
        $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
        grant usage on schema public,auth to anon,authenticated,service_role;
        grant execute on function auth.uid() to authenticated,service_role;
        create schema storage;
        create table storage.buckets(id text primary key,name text,public boolean);
        """)
        c.execute((Path(__file__).parents[1] / 'supabase/migrations/202609190001_supertonic_backend.sql').read_text())
        c.execute('insert into auth.users values(%s),(%s)', (A, B))
    yield uri
    conn.close()
    server.cleanup()


@pytest.fixture
def db(database):
    conn = psycopg2.connect(database)
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute('truncate public.documentos cascade')
    yield conn
    conn.close()


def create_job(c, owner=A):
    c.execute("insert into public.documentos(owner_id,text) values(%s,'hello') returning id", (owner,))
    document = c.fetchone()[0]
    c.execute("""insert into public.jobs(owner_id,document_id,model,config,plan,cache_key)
                 values(%s,%s,'model@1','{}','["hello"]',repeat('a',64)) returning id""", (owner, document))
    return c.fetchone()[0], document


def claim(c):
    c.execute('select id,claim_token from public.st_claim_job(%s,120)', (WORKER,))
    return c.fetchone()


def test_owner_rls_and_read_only(db):
    with db.cursor() as c:
        ja, _ = create_job(c, A)
        create_job(c, B)
        c.execute('set role authenticated')
        c.execute("select set_config('request.jwt.claim.sub',%s,false)", (A,))
        c.execute('select id from public.jobs')
        assert c.fetchall() == [(ja,)]
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            c.execute("update public.jobs set status='error'")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            c.execute('select * from public.shares')
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            claim(c)
        c.execute('set role anon')
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            c.execute('select * from public.jobs')


def test_owner_cannot_reference_another_document(db):
    with db.cursor() as c:
        _, document = create_job(c, A)
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            c.execute("""insert into public.jobs(owner_id,document_id,model,config,plan,cache_key)
              values(%s,%s,'m','{}','["x"]',repeat('b',64))""", (B, document))


def test_claim_checkpoint_finish_and_stale_fencing(db):
    with db.cursor() as c:
        j, _ = create_job(c)
        c.execute('set role service_role')
        claimed, old_token = claim(c)
        assert claimed == j
        assert claim(c) is None
        # Expire the lease using test admin, then claim again as a worker.
        c.execute('reset role')
        c.execute("update public.jobs set lease_until=now()-interval '1 second' where id=%s", (j,))
        c.execute('set role service_role')
        _, new_token = claim(c)
        assert old_token != new_token
        old_path = f'{A}/{j}/{old_token}/chunk.wav'
        with pytest.raises(psycopg2.Error, match='Lost claim'):
            c.execute('select public.st_checkpoint(%s,%s,0,%s)', (j, old_token, old_path))
        c.execute('select public.st_heartbeat(%s,%s,120)', (j, old_token))
        assert c.fetchone()[0] is False
        new_path = f'{A}/{j}/{new_token}/chunk.wav'
        with pytest.raises(psycopg2.Error, match='Incomplete chunks'):
            c.execute('select public.st_finish(%s,%s,%s)', (j, new_token, new_path))
        c.execute('select public.st_checkpoint(%s,%s,0,%s)', (j, new_token, new_path))
        assert c.fetchone()[0]['audio_path'] == new_path
        c.execute('select public.st_finish(%s,%s,%s)', (j, new_token, new_path))
        assert c.fetchone()[0]['status'] == 'done'
        c.execute('select claim_token,lease_until from public.jobs where id=%s', (j,))
        assert c.fetchone() == (None, None)


def test_skip_locked_candidate(db, database):
    with db.cursor() as c:
        first, _ = create_job(c)
        second, _ = create_job(c)
    locked = psycopg2.connect(database)
    try:
        with locked.cursor() as c:
            c.execute('select id from public.jobs where id=%s for update', (first,))
        with db.cursor() as c:
            c.execute('set role service_role')
            claimed, _ = claim(c)
            assert claimed == second
    finally:
        locked.rollback()
        locked.close()


def test_null_owner_rejected_and_buckets_private(db):
    with db.cursor() as c:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            c.execute("insert into public.documentos(owner_id,text) values(null,'x')")
        c.execute('select bool_and(not public),count(*) from storage.buckets')
        assert c.fetchone() == (True, 2)
