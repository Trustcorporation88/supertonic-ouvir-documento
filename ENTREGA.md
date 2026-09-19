# SuperTonic — entrega de desenvolvimento

Base: 74709583001b1122707d7df2e43aab54f048e9df. Preparado em 19/09/2026.

## Estado
Esta é uma entrega parcial de desenvolvimento, NÃO um deploy concluído ou integração ponta a ponta de todas as propostas. Nada foi enviado ao GitHub, Railway ou banco Supabase real. Não substituir produção sem revisão e homologação.

## Conectado ao servidor/interface
- Uploads temporários em disco com limite incremental e limite do corpo HTTP.
- Fila limitada; /usar usa o mesmo processamento.
- Montagem de áudio incremental sem acumular todos os arrays de chunks.
- Cancelamento cooperativo e limpeza de jobs terminais.
- Seleção de páginas limitada; confiança de proxies configurável.
- Cache com chave ampliada e publicação atômica.
- Downloads remotos desativados por padrão. Isso desabilita links YouTube também. A habilitação opt-in NÃO implementa proteção completa contra SSRF: requer isolamento de saída/rede.
- Correções de normalização pt-BR, moedas, temperatura e contexto jurídico.
- EPUB conectado à extração e aceito na interface (limite próprio de 64 MiB, limites de XML/ZIP).
- Polling adaptativo com backoff, suspensão em aba oculta/offline e melhorias de acessibilidade.
- Docker copia os módulos obrigatórios novos.

## Módulos prontos, NÃO conectados à experiência final
- document_features.export_m4b: exportação FFmpeg com capítulos e capa opcional. Ainda não aparece como formato no player nem usa timestamps do TTS real. EPUB na rota atual é achatado em texto, sem exportação de capítulos.
- supabase_backend.py e supabase/migrations/: autenticação, jobs persistentes, RLS, buckets privados, compartilhamento, cache por dono e leases. Ainda NÃO chamados por server.py. Não há login Supabase na interface, Realtime ou recuperação de jobs via banco em execução.
- A aplicação em modo local mantém jobs públicos por identificador: não tratar documentos como privados só por haver módulo Supabase no pacote. Requer camada de propriedade/autorização em TODAS rotas antes de exposição multiusuário.

## Próxima integração obrigatória
1. Escolher projeto Supabase explicitamente. Inspecionar esquema existente antes de aplicar migração.
2. Conectar auth do servidor/cliente; UUID completo; propriedade em criação, leitura, chunks, download, cancelamento e share.
3. Conectar upload privado e persistência de chunks/progresso com chamadas SDK fora do loop assíncrono.
4. Migrar o worker local para claim/lease/heartbeat, com idempotência e recuperação após reinício.
5. Adicionar Realtime autorizado com snapshot inicial/reconexão e fallback; não remover polling antes disso.
6. Testar isolamento de dois usuários, JWT expirado, compartilhamento revogado/expirado, cancelamento e retomada real.
7. Conectar M4B a timestamps reais, cache, MIME e interface.

## Não implementado
Podcast/resumo LLM; sincronização palavra a palavra; streaming binário direto; SSML; motor TTS alternativo/mixagem; multi-workers; OCR de PDFs escaneados; metadados ID3 no MP3. Propostas e critérios em docs/ROADMAP.md; esse documento não é benchmark executado.

## Testes
Consolidação local: executar `python -m pytest -q test_backend.py tests/test_textnorm_features.py tests/test_document_features.py tests/test_supabase_backend.py tests/test_supabase_sql_local.py` e `node --test tests/frontend.test.cjs`.
Logs da consolidação em docs/validation/. Os relatórios individuais preservados são evidências de execuções separadas. Os testes do servidor usam stubs do modelo, não validam qualidade sonora ou desempenho TTS. Testes PostgreSQL locais requerem pgserver e psycopg2; quando ausentes, o módulo é ignorado. Auth/Storage Supabase reais não foram exercitados.

## Instalação e limites
requirements.txt continua a instalação principal. O módulo Supabase opcional usa supabase==2.31.0 (não necessário para o servidor atual); não exponha service role ao navegador. Para testes: pytest, fastapi, python-multipart, httpx, uvicorn, numpy, soundfile, num2words; FFmpeg ou imageio-ffmpeg para testes de exportação. Não houve build Docker nesta consolidação.
Leia BACKEND_HARDENING.md, REPORT.md, docs/SUPABASE_BACKEND.md e docs/document_features_integration.md. Não use o SQL permissivo publicado anteriormente na conversa.
