# Backend Supabase opcional — integração ainda NÃO ativada

Base inspecionada: `74709583001b1122707d7df2e43aab54f048e9df` de `Trustcorporation88/supertonic-ouvir-documento`.

## Entrega e limites

Este pacote adiciona somente `supabase_backend.py`, uma migração e testes/documentação. **Não altera `server.py`, frontend ou requirements; não aplica nada em projeto Supabase real.** Não é uma integração ponta a ponta pronta: executar o servidor original continuará usando `JOBS`, `JOBS_DIR`, `_cache`, `SHARE_DIR` e a fila em memória.

No código inspecionado, `Job.__init__` gera `uuid.uuid4().hex[:12]`; `_cache_key`, `_restore_from_cache` e `_save_to_cache` são locais; `_worker` chama síntese; as rotas `/api/jobs`, chunks, áudio e `/s/{token}` consultam armazenamento local. A API key opcional atual não representa proprietário Supabase. Esses caminhos precisam ser substituídos explicitamente — adicionar este arquivo não os protege.

## Segurança implementada

- Cada método voltado ao proprietário recebe o access token JWT e chama **`auth.get_user(jwt)` no servidor**, pela rede. O proprietário vem exclusivamente de `response.user.id`. Não se confia em `get_session`, decode local ou `owner_id` enviado pelo cliente. Falha de Auth resulta em negação, inclusive indisponibilidade de rede (a aplicação decide a mensagem externa).
- Dois clientes separados: um de Auth com publishable key e outro administrativo com service role, sem persistência/refresh de sessão. Nunca chamar `set_session`/`sign_in` no administrativo. O backend usa service role, que ignora RLS; por isso TODAS as consultas do usuário filtram proprietário explicitamente. RLS é proteção adicional para acesso direto, não substituto desses filtros.
- UUIDs canônicos completos em jobs, documentos, workers e claim tokens. IDs curtos antigos são rejeitados. Não há compatibilidade/migração automática dos diretórios legados.
- `owner_id NOT NULL` nas quatro tabelas; FKs compostas impedem job/documento e share/job de proprietários diferentes. RLS habilitada com políticas `auth.uid() = owner_id`, sem políticas abertas. Clientes autenticados têm somente SELECT de seus documentos/jobs/chunks; nenhuma escrita direta. `shares` não tem sequer grant SELECT para clientes (a política de proprietário existe como defesa adicional).
- Buckets `supertonic-audio` e `supertonic-documentos` privados, sem políticas Storage públicas adicionadas. Upload/download/assinatura deste módulo usam somente backend. O bucket documentos está **reservado**: nesta versão o texto extraído persiste em `documentos.text`; upload do arquivo original NÃO está implementado.
- Tokens share: 32 bytes aleatórios, somente SHA-256 persistido; token bruto devolvido uma vez. Busca por hash apenas no backend administrativo, sem função pública de resolução nem SELECT anônimo. Token é credencial bearer: qualquer pessoa que o possuir acessa até expirar/revogar.
- URL assinada: máximo 60s. Share tem prazo máximo 7 dias; TTL assinado é o menor entre pedido, 60s e tempo restante, menos 2s de margem. O backend também verifica o `exp` da resposta confiável do Storage e **recusa entregar** URL cujo prazo ultrapasse `expires_at` (inclusive clock skew/latência maior que a margem). Essa leitura de metadados da URL gerada pelo próprio Storage NÃO autentica usuários: Auth continua obrigatoriamente em `get_user`. Mudança no formato de tokens Storage falha fechada e exigirá adaptação/teste.
- Revogação bloqueia novas resoluções. **URLs já emitidas permanecem válidas até seu próprio vencimento**, no máximo 60s; revogação instantânea exigiria streaming/proxy autorizado no backend. Não colocar tokens/URLs em logs; usar HTTPS, `Cache-Control: no-store`, `Referrer-Policy: no-referrer` e rate limiting no endpoint de share. Responder genericamente 404 para inválido/revogado/expirado.
- Cache inclui proprietário, texto-fonte, plano de chunks normalizados, revisão de modelo e configuração JSON canônica. Fornecer revisão real de pesos/modelo e todas as opções relevantes: voz/revisão, idioma, speed, steps, pitch se houver, formato, sample rate, pausa, versão do normalizador/splitter/encoder. Não usar cache local antigo compartilhado. `cached_job` apenas encontra job completo do mesmo dono; não copia áudio nem altera o novo job automaticamente.

## Persistência e lease

`create_document` persiste texto; `create_job` persiste modelo/config/plano **antes** de um worker pegar o trabalho. `claim_job` usa transação SQL, `FOR UPDATE SKIP LOCKED`, gera novo claim token e expiração; suporta fila e takeover de lease vencido. Retorna o registro completo ou `None`.

Fluxo a implementar no worker:

1. Um UUID completo identifica o processo. Chamar `claim_job(worker_id)`; não usar fila em memória como fonte de verdade.
2. Ler `worker_chunks(job)`. Os índices persistidos sobrevivem ao reinício; baixar com `download_chunk(job, chunk)` e gerar apenas índices ausentes do `job['plan']`. Se o objeto remoto não existir, regenerar seu índice.
3. Renovar com `heartbeat(job['id'], job['claim_token'])` a cada ~30s para lease padrão de 120s. Se false, parar de produzir/commitar. Síntese longa não pode impedir o heartbeat; usar thread/tarefa separada. Worker heartbeats não usam o JWT do usuário, que pode expirar durante execução longa.
4. Persistir resultado com `save_chunk(job, token, index, wav_bytes)`. RPC verifica lease/token sob lock; checkpoint é UPSERT idempotente por índice. Upload gera nome imutável único sob `owner/job/claim/`, evitando que worker antigo sobrescreva o novo.
5. Montar áudio completo a partir dos chunks duráveis e chamar `finish_job`. RPC só conclui se todos os chunks existirem no banco e claim estiver vigente. Grava caminho final e limpa lease/token. Se erro terminal, `fail_job` é também condicionado ao token/lease.

`worker_chunks`, `download_chunk`, `claim_job`, `heartbeat`, `save_chunk`, `finish_job`, `fail_job` são **capacidades administrativas internas**. Não expor diretamente em rotas que aceitem IDs/job dict/claim token do cliente. Usar somente registros retornados pelo claim. Workers processam proprietários diferentes por desenho, com chave somente no servidor.

Upload Storage e commit SQL não são uma única transação. Uma queda após upload e antes do checkpoint deixa objeto órfão. Retry pode gerar objeto extra; dado durável só é o apontado por SQL. Planejar limpeza de órfãos conservadora (janela maior que leases/retries), retenção e remoção de objetos após apagar usuários/jobs. Cascades SQL não apagam Storage. `attempts` é contado, mas não há política automática de limite/backoff, cancelamento, requeue de erro terminal, garbage collection ou quota nesta versão. Também não há coordenação distribuída da GPU.

## Preparar dependências e configuração — sem alteração automática

O módulo usa import tardio de `supabase`, portanto os mocks rodam sem SDK. Para ativação futura, instalar deliberadamente num ambiente de teste (não alteramos requirements):

```sh
python -m pip install 'supabase==2.31.0'
```

Contrato de construção conferido com 2.31.0 neste trabalho. Não implica validação de todas as versões futuras. Configurar `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` e `SUPABASE_SERVICE_ROLE_KEY` somente no servidor. Service role nunca vai ao frontend, Git, logs ou ZIP. Nenhuma credencial real está no pacote.

O SDK é síncrono. **Não chamar métodos diretamente dentro de `async def`**. Exemplo de padrão, não uma rota instalada:

```python
import asyncio
import os
from supabase_backend import create_backend

def load_job_sync(access_token, job_id):
    # Cliente por chamada/thread: não compartilhar estado Auth mutável entre usuários.
    backend = create_backend(
        os.environ['SUPABASE_URL'],
        os.environ['SUPABASE_PUBLISHABLE_KEY'],
        os.environ['SUPABASE_SERVICE_ROLE_KEY'],
    )
    return backend.get_job(access_token, job_id)

# dentro da futura rota async, após extrair Authorization: Bearer <token>:
# row = await asyncio.to_thread(load_job_sync, access_token, job_id)
```

Para alta carga, usar worker/cliente de longa duração por thread, encerramento dos transportes e executor limitado/backpressure; não criar clientes indefinidamente sem gerenciar recursos. Nunca alternar sessões de usuários num singleton. `to_thread` evita bloquear o loop, não dá cancelamento forte do HTTP nem exclusão mútua. Configurar timeouts HTTP e dimensionar executor para que heartbeat não fique atrás de síntese pesada; separar clientes/thread dos heartbeats.

## Checklist de integração no servidor (trabalho futuro)

1. Adicionar login/session no frontend e dependência Bearer nas rotas privadas; eliminar fallback anônimo para jobs/cache. API key legada não é usuário. Não expor chaves administrativas.
2. Na criação, extrair/normalizar/splitar entrada, gravar documento/job com UUID completo e devolver `id` persistido. Adaptar o objeto `Job`/payload público e diretórios temporários. `create_job` espera plano já final, não executa extração/síntese.
3. Substituir worker/fila/cache/shares locais pelos métodos acima. Definir estratégia de fila/prioridade e limites de concorrência. Contar progresso pelos chunks persistidos; o schema não reproduz todos os campos locais `stage`, `message`, `duration`, `percent` automaticamente.
4. Fazer `/api/jobs/{id}` e endpoints chunks/áudio verificarem JWT e dono antes de assinar. `audio_url`/`chunk_url` cobrem assinatura; redirecionamento versus JSON é decisão da rota. Não manter FileResponse acessível sem autenticação.
5. Rotas de share devem usar `create_share`/`resolve_share`/`revoke_share`. Só áudio final é compartilhado; texto/título não são retornados por `resolve_share`. Rate-limit e redigir logs. Nunca usar token como caminho local.
6. Implementar exclusão/retention, limpeza Storage, política de retries e migração deliberada de dados antigos. Não inventar owner para jobs legados: exigir associação confiável ou expirar dados.

## Aplicação SQL e validação antes de produção

Não foi aplicada em projeto real. SQL está em `supabase/migrations/202609190001_supertonic_backend.sql`, transacional e deliberadamente não idempotente. Cria tabelas/buckets próprios; se esses nomes já existem, falha em vez de alterar políticas/schemas silenciosamente. Testar em Supabase local/dev e revisar antes de migrar produção.

Antes de aplicar: revisar privilégios/default privileges e políticas **preexistentes** de `storage.objects`; uma política ampla já instalada pode abrir buckets privados. A migração não apaga políticas alheias. Confirmar schema auth/storage padrão, backups e estratégia de rollout. Depois, executar testes com dois usuários reais, usuário anônimo, tokens vencidos, share expirado/revogado, concorrência de workers, Storage faltante e restart. Rodar advisors de segurança no projeto somente quando aplicação for autorizada.

### Testes incluídos

```sh
python -m pytest -q tests/test_supabase_backend.py
# Opcional: PostgreSQL descartável local, sem conexão Supabase:
python -m pip install pgserver psycopg2-binary
python -m pytest -q tests/test_supabase_backend.py tests/test_supabase_sql_local.py
```

A suíte SQL inicializa um PostgreSQL temporário e schemas `auth`/`storage` **mínimos simulados**. Executa migração real, RLS owner/read-only/anon, FKs entre donos, buckets privados, claim SKIP LOCKED, takeover, fencing, checkpoints e conclusão. Não é emulador completo Supabase. Sem dependências, o arquivo SQL é marcado skipped, não contado como sucesso. Testes mock não fazem tráfego nem provam a política de um projeto externo.

Limitações da validação: não houve login real, PostgREST real, upload/assinatura Storage real, execução de síntese, teste de consumo frontend ou integração de rotas. A garantia end-to-end depende da adaptação e testes acima. Arquivo `docs/SUPABASE_VALIDATION.txt` registra o resultado observado.

## Referências consultadas via ferramenta de documentação Supabase

- https://supabase.com/docs/reference/python/auth-getuser — `get_user(jwt)`.
- https://supabase.com/docs/reference/python/storage-from-createsignedurl — `create_signed_url(path, seconds)`.
- https://supabase.com/docs/guides/database/postgres/row-level-security — RLS, `auth.uid()` e bypass de service role.
