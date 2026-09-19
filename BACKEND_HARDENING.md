# Backend: controles de recursos e segurança

Base: `74709583001b1122707d7df2e43aab54f048e9df`.
Arquivos do patch: `server.py`, `backend_resources.py`, `test_backend.py` e este documento.
Nenhuma alteração em `textnorm.py`, `static/`, Supabase, dependências de produção ou deploy.

## Alterações e compatibilidade

- `/api/jobs` e `/usar`: uploads copiados em blocos de 64 KiB para arquivo temporário; os jobs guardam `Path`, nunca o conteúdo binário. PDF/DOCX/imagem recebem caminhos; mídia usa diretamente o arquivo, sem segunda cópia integral. Texto simples lê no máximo `MAX_TEXT_CHARS * 4 + 1` bytes. Arquivos de entrada são removidos após conclusão/erro/cancelamento reconhecido, inclusive fila cheia.
- Middleware ASGI conta os bytes efetivamente recebidos, inclusive sem Content-Length, antes do parser multipart: teto total de `MAX_UPLOAD_MB` MiB + 1 MiB de envelope. Cada upload aceito tem teto exato `MAX_UPLOAD_MB` MiB e falha com 413. O parser Starlette ainda usa spool temporário próprio antes da cópia; isto não é zero-copy nem elimina seu pequeno buffer inicial em memória. A proteção total abrange também rotas `/v1/*` herdadas. O importador de estilos upstream não foi reescrito: já lê um tamanho pequeno explicitamente limitado, não entra na fila de documentos.
- Fila de documentos limitada por `QUEUE_MAX_SIZE` (16 por padrão), mais um job em execução. Fila cheia retorna 429 com `error.code=queue_full`; não aguarda indefinidamente segurando upload. `/usar` usa a mesma fila, saída em arquivo e headers legados `X-Texto`, `X-Duration-Seconds`, `X-Truncated`. Preview de voz continua WAV. Rotas, campos de progresso, chunks e links finais da UI foram mantidos.
- Síntese escreve um bloco de cada vez em WAV e publica cada chunk após fechá-lo. WAV final é incremental; OGG/FLAC são convertidos em blocos de 65536 frames; MP3 usa FFmpeg cancelável. Não há lista de arrays nem concatenação do áudio inteiro. O PCM intermediário é 16-bit (mesma saída WAV legada; há quantização antes da conversão OGG).
- DELETE pede cancelamento via `threading.Event`; o worker só marca `cancelled` e remove arquivos após reconhecer o pedido. Não apaga diretório de síntese ativa. Checagens entre fases/blocos/segmentos, antes de publicação, e durante subprocessos de compactação/codificação. Shutdown espera a thread cooperar antes de liberar o modelo. `QUEUE.task_done()` também é chamado.
- Janitor remove jobs **terminais** (`done/error/cancelled`) usando horário de término, não idade de criação. Não remove jobs em fila/execução. Cache em publicação tem diretório oculto separado e não é coletado como cache pronto.
- `parse_pages`: especificação <= 2048 caracteres, números <= 12 dígitos, intervalos limitados antes de iterar; PDFs > 10000 páginas recusados. Intervalos invertidos continuam válidos.
- Cache inclui modelo, versão instalada do engine, sample rate, revisão explícita, hash do normalizador, texto, voz, idioma, velocidade, pausas, formato e bitrate. Vozes customizadas não usam cache (um mesmo nome pode mudar de conteúdo). Publicação em diretório temporário único + rename atômico, sem apagar entrada já publicada. `CACHE_REVISION` deve mudar quando pesos/configuração externos mudarem sem mudar o identificador do modelo.

## SSRF: default seguro por desativação, não por DNS prévio

`ALLOW_REMOTE_DOWNLOADS=0` (default): URLs são recusadas com 403 e código `remote_download_disabled` nas duas rotas, antes de yt-dlp/urllib/transcrição. `_download_media` verifica novamente a opção. `/health` expõe `remote_downloads=false`. A aba de link permanece visível porque a UI não foi editada; mostra o erro indicando upload de arquivo.

**`ALLOW_REMOTE_DOWNLOADS=1` é opt-in inseguro, não uma proteção SSRF.** Mantém o downloader legado para ambientes controlados. Não há promessa de bloquear IPs privados, metadados de nuvem, DNS rebinding, redirects, manifestos ou requisições secundárias de yt-dlp. Uma checagem DNS prévia não resolveria isso. Não habilite em serviço público sem isolamento de rede/egress que se aplique a todas as conexões, resoluções, redirects e processos filhos. A rota `/usar` com URL, quando habilitada deliberadamente, mantém o contrato JSON de transcrição sem TTS.

FFmpeg da compactação local usa `-protocol_whitelist file,pipe`, mas **isso não constitui isolamento geral de documentos/mídias maliciosos**; outros parsers e o fallback de transcrição existem. Parser/codec deve rodar em ambiente sem acesso a redes/arquivos sensíveis se o serviço aceitar arquivos hostis. Chamadas OpenAI configuradas pelo operador continuam possíveis; não são downloads de URLs fornecidas pelo cliente.

## Proxy

`TRUSTED_PROXIES` default vazio: ignora X-Forwarded-For/Proto. Configure IPs/CIDRs dos proxies reais, separados por vírgula, por exemplo `10.20.0.5/32`. A cadeia XFF é percorrida da direita para esquerda enquanto o próximo remetente for confiável. O proxy deve sanitizar/anexar corretamente os cabeçalhos. Não use `0.0.0.0/0` ou `::/0` como atalho.

`python server.py` inicia Uvicorn com `proxy_headers=False` para evitar confiança dupla. Se iniciar por outro comando, use `uvicorn server:app --no-proxy-headers` e deixe esta aplicação aplicar a lista. URL de compartilhamento ainda usa Host do request: configure validação/sanitização de Host no reverse proxy.

## Limitações deliberadas

- Um processo/um worker de aplicação. Jobs, rate limit e posições da fila são em memória; não há retomada após crash nem coordenação entre vários Uvicorn workers. Não executar múltiplos workers sobre o mesmo diretório. Arquivos órfãos após crash exigem limpeza operacional com serviço parado.
- Limites por request/fila não são quota total de disco nem limite de conexões simultâneas. Jobs terminados/cache/shares podem ocupar disco até seus TTLs. Configure quota de volume, concorrência, timeout e limite de corpo também no proxy.
- Uma chamada de síntese ONNX, extração PDF/DOCX/OCR, carregamento de modelo ou request OpenAI já em andamento não é interrompida à força. Cancelamento é cooperativo; o shutdown pode aguardar essa fase terminar. Nenhuma thread ativa tem seus arquivos apagados antecipadamente.
- Parsers PDF/DOCX/imagem ainda podem expandir muito em RAM/CPU; limite de upload e de páginas não é proteção completa contra decompression bombs. Texto extraído pode exceder `MAX_TEXT_CHARS` antes do truncamento. Testes não medem RSS máximo.
- `/v1/tts`, `/v1/audio/speech` e batch são implementação do pacote upstream: não entram nesta fila nem receberam a reescrita de áudio incremental. Os controles de documentos se aplicam às rotas próprias `/api/jobs` e `/usar`; mantenha API_KEY e limites de acesso para `/v1/*`.
- Download remoto opt-in conserva limitações legadas (inclusive subprocessos/redirecionamentos e limites de download); não foi validado como seguro. Não foi executado em teste.
- Sem download de modelos ou testes de qualidade de voz. OCR, transcrição real e infraestrutura de proxy não foram executados. Testes usam engine/app stub, mas FastAPI, multipart, soundfile, cache em disco e subprocesso de cancelamento reais.

## Testes reproduzíveis

Em ambiente com Python, `pytest`, `fastapi`, `httpx`, `python-multipart`, `numpy`, `soundfile` e `uvicorn`:

```sh
python -m pytest -q test_backend.py
python -m py_compile server.py backend_resources.py
git diff --check
```

Resultado: **30 passed**, 2 avisos de depreciação de Starlette/AnyIO no ambiente de execução. Cobertura: páginas enormes/invertidas/inválidas; upload incremental e limpeza; HTTP nas duas rotas; fila cheia; headers e áudio legado; chunks UI; SSRF desativado; proxy e prefixo XFF forjado; áudio incremental WAV/OGG/FLAC; chave e publicação concorrente de cache; vozes customizadas; cancelamento em fila/execução/subprocesso/transcrição; janitor terminal; contrato remoto legado com downloader/transcritor stub.
