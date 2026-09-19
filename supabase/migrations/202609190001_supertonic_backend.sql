-- Optional, additive migration. Review/test locally before applying.
-- Deliberately fails on existing conflicting table names (never silently weakens them).
begin;
create table public.documentos (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 title text not null default '', text text not null,
 created_at timestamptz not null default now(), unique(id, owner_id)
);
create table public.jobs (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 document_id uuid not null,
 model text not null check (length(model)>0), config jsonb not null,
 plan jsonb not null check (jsonb_typeof(plan)='array' and jsonb_array_length(plan)>0),
 cache_key text not null check (cache_key ~ '^[0-9a-f]{64}$'),
 status text not null default 'queued' check (status in ('queued','running','done','error')),
 audio_path text,
 worker_id uuid, claim_token uuid, lease_until timestamptz,
 attempts integer not null default 0,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(id, owner_id),
 foreign key(document_id, owner_id) references public.documentos(id,owner_id) on delete cascade,
 check (audio_path is null or audio_path like owner_id::text || '/' || id::text || '/%'),
 check ((status='running' and worker_id is not null and claim_token is not null and lease_until is not null)
     or (status<>'running' and worker_id is null and claim_token is null and lease_until is null)),
 check (status<>'done' or audio_path is not null)
);
create table public.chunks (
 job_id uuid not null, owner_id uuid not null references auth.users(id) on delete cascade,
 chunk_index integer not null check(chunk_index>=0), audio_path text not null,
 created_at timestamptz not null default now(), primary key(job_id,chunk_index),
 foreign key(job_id,owner_id) references public.jobs(id,owner_id) on delete cascade,
 check(audio_path like owner_id::text || '/' || job_id::text || '/%')
);
create table public.shares (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade, job_id uuid not null,
 token_hash text not null unique check(token_hash ~ '^[0-9a-f]{64}$'),
 created_at timestamptz not null default now(), expires_at timestamptz not null,
 revoked_at timestamptz,
 foreign key(job_id,owner_id) references public.jobs(id,owner_id) on delete cascade,
 check(expires_at>created_at and expires_at<=created_at + interval '7 days')
);
create index st_documents_owner on public.documentos(owner_id);
create index st_jobs_owner_cache on public.jobs(owner_id,cache_key) where status='done';
create index st_jobs_document on public.jobs(document_id,owner_id);
create index st_jobs_claim on public.jobs(status,lease_until,created_at) where status in ('queued','running');
create index st_chunks_owner on public.chunks(owner_id);
create index st_shares_owner_job on public.shares(owner_id,job_id);
alter table public.documentos enable row level security;
alter table public.jobs enable row level security;
alter table public.chunks enable row level security;
alter table public.shares enable row level security;
-- Client access is read-only. Only backend service_role can mutate server-owned state.
create policy st_documents_owner on public.documentos for select to authenticated using ((select auth.uid())=owner_id);
create policy st_jobs_owner on public.jobs for select to authenticated using ((select auth.uid())=owner_id);
create policy st_chunks_owner on public.chunks for select to authenticated using ((select auth.uid())=owner_id);
create policy st_shares_owner on public.shares for select to authenticated using ((select auth.uid())=owner_id);
revoke all on public.documentos, public.jobs, public.chunks, public.shares from public, anon, authenticated;
grant select on public.documentos, public.jobs, public.chunks to authenticated;
-- No client grants on shares, even to authenticated. Resolution is backend only.
grant all on public.documentos, public.jobs, public.chunks, public.shares to service_role;

insert into storage.buckets(id,name,public) values
 ('supertonic-audio','supertonic-audio',false),
 ('supertonic-documentos','supertonic-documentos',false);
-- No anon/storage object policies. Upload/signing are backend-only.
-- Private buckets alone are not sufficient if the project has broad existing policies:
-- inspect existing storage.objects policies before deployment.

create function public.st_claim_job(p_worker uuid, p_seconds integer default 120)
returns setof public.jobs language plpgsql security invoker set search_path='' as $$
begin
 if p_worker is null or p_seconds not between 10 and 900 then raise exception 'Invalid lease'; end if;
 return query
 with candidate as (
  select id from public.jobs where status='queued'
   or (status='running' and lease_until<clock_timestamp())
  order by created_at for update skip locked limit 1
 )
 update public.jobs j set status='running',worker_id=p_worker,claim_token=gen_random_uuid(),
  lease_until=clock_timestamp()+make_interval(secs=>p_seconds),attempts=attempts+1,
  updated_at=clock_timestamp()
 from candidate c where j.id=c.id returning j.*;
end; $$;

create function public.st_heartbeat(p_job uuid,p_token uuid,p_seconds integer default 120)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 if p_seconds not between 10 and 900 then raise exception 'Invalid lease'; end if;
 update public.jobs set lease_until=clock_timestamp()+make_interval(secs=>p_seconds),updated_at=clock_timestamp()
 where id=p_job and status='running' and claim_token=p_token and lease_until>clock_timestamp();
 return found;
end; $$;

create function public.st_checkpoint(p_job uuid,p_token uuid,p_index integer,p_path text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare j public.jobs; result jsonb;
begin
 select * into j from public.jobs where id=p_job for update;
 if not found or j.status<>'running' or j.claim_token is distinct from p_token
    or j.lease_until<=clock_timestamp() then raise exception 'Lost claim'; end if;
 if p_index is null or p_index<0 or p_index>=jsonb_array_length(j.plan)
    or p_path is null or p_path not like j.owner_id::text||'/'||j.id::text||'/'||p_token::text||'/%'
    or p_path ~ '(^|/)\.\.(/|$)' then raise exception 'Invalid checkpoint'; end if;
 insert into public.chunks(job_id,owner_id,chunk_index,audio_path)
 values(j.id,j.owner_id,p_index,p_path)
 on conflict(job_id,chunk_index) do update set audio_path=excluded.audio_path
 returning to_jsonb(chunks.*) into result;
 update public.jobs set updated_at=clock_timestamp() where id=p_job;
 return result;
end; $$;

create function public.st_finish(p_job uuid,p_token uuid,p_path text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare j public.jobs; result jsonb;
begin
 select * into j from public.jobs where id=p_job for update;
 if not found or j.status<>'running' or j.claim_token is distinct from p_token
    or j.lease_until<=clock_timestamp() then raise exception 'Lost claim'; end if;
 if (select count(*) from public.chunks where job_id=j.id)<>jsonb_array_length(j.plan)
 then raise exception 'Incomplete chunks'; end if;
 if p_path is null or p_path not like j.owner_id::text||'/'||j.id::text||'/'||p_token::text||'/%'
    or p_path ~ '(^|/)\.\.(/|$)' then raise exception 'Invalid audio path'; end if;
 update public.jobs set status='done',audio_path=p_path,worker_id=null,claim_token=null,
  lease_until=null,updated_at=clock_timestamp() where id=p_job returning to_jsonb(jobs.*) into result;
 return result;
end; $$;

create function public.st_fail(p_job uuid,p_token uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 update public.jobs set status='error',worker_id=null,claim_token=null,lease_until=null,
 updated_at=clock_timestamp()
 where id=p_job and status='running' and claim_token=p_token and lease_until>clock_timestamp();
 return found;
end; $$;
revoke all on function public.st_claim_job(uuid,integer), public.st_heartbeat(uuid,uuid,integer),
 public.st_checkpoint(uuid,uuid,integer,text), public.st_finish(uuid,uuid,text), public.st_fail(uuid,uuid)
 from public,anon,authenticated;
grant execute on function public.st_claim_job(uuid,integer), public.st_heartbeat(uuid,uuid,integer),
 public.st_checkpoint(uuid,uuid,integer,text), public.st_finish(uuid,uuid,text), public.st_fail(uuid,uuid)
 to service_role;
commit;
