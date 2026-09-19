# Frontend SuperTonic — entrega para integração

## Base e escopo

- Repositório: https://github.com/Trustcorporation88/supertonic-ouvir-documento
- Commit clonado: `74709583001b1122707d7df2e43aab54f048e9df`.
- Apenas arquivos de aplicação alterados: `static/app.js`, `static/index.html`, `static/sw.js`.
- Testes e relatório produzidos separadamente; nenhum arquivo Python/backend, CSS ou dependência do projeto foi alterado. Nenhum commit ou push foi feito.
- Não foi adicionado Supabase client, autenticação improvisada, SSE, parser EPUB ou endpoint novo.

## Implementação

### Polling e recuperação

- GETs de estado sequenciais, sem `setInterval` e sem requisições simultâneas pelo loop do job.
- Com progresso novo: intervalo de 700 ms; em fila: 2 s. Sem mudança: multiplicação por 1,5 até 5 s (em execução) ou 10 s (fila).
- Mudanças observadas: status, etapa, percentual, posição da fila, quantidade de chunks e mensagem. O contrato atual do backend continua sendo usado integralmente, sem inventar ETag, delta ou SSE.
- Aba oculta ou navegador offline: não inicia novos GETs de estado/health/vozes/arquivo final; aborta GET monitorado em voo. Esperas ficam em eventos de visibilidade/conectividade, sem loop de requisições. Ao retornar, continua respeitando eventual prazo mínimo de backoff.
- Erros de rede, timeout, JSON inválido e HTTP 408/429/5xx: backoff de 1, 2, 4, 8, 16 e no máximo 30 s, respeitando `Retry-After` maior (segundos ou data HTTP). Retenta enquanto o acompanhamento estiver ativo; o usuário pode cancelar após obter o ID.
- HTTP não transitório, como 401/403/404/422, termina o acompanhamento com erro. Não há reenvio automático do POST de criação, evitando jobs duplicados.
- Timeout de leitura: 15 s para JSON e 120 s para áudio, incluindo o corpo da resposta. Uma transferência parcial abortada pode precisar ser retomada do início; não foi implementado Range/resume.
- Depois de `done`, download/retentativa do áudio ocorre separado: não baixa novamente o estado inteiro a cada tentativa de áudio.
- Revoga URL de áudio final anterior ao iniciar outro pedido ou cancelar, e grava no histórico a voz efetivamente submetida.

### Cancelamento examinado

- Usa o endpoint existente `DELETE /api/jobs/{id}` — sem inventar contrato.
- O botão aparece após receber o ID. Antes disso o upload/POST não é abortado deliberadamente: sem ID/idempotência não seria possível limpar com segurança um job que o servidor já criou.
- Ao clicar, aborta polling/download final/esperas, interrompe e limpa o player, oculta resultado parcial, solicita DELETE uma única vez e devolve foco ao botão de gerar quando apropriado.
- DELETE falho/timeout informa explicitamente que o cancelamento remoto não foi confirmado. Sucesso é apresentado como **cancelamento solicitado**, não como garantia de interrupção de CPU.
- Estado remoto `cancelled` termina o loop e limpa reprodução, em vez de ficar consultando indefinidamente.

**Limitação real do backend na base:** `delete_job` remove o job e sua pasta imediatamente. `_run_job_sync` não consulta `cancelled` durante execução, e o worker pode continuar acessando a pasta removida ou concluir/cachear saída depois. Cancelamento de jobs ainda enfileirados é observado pela checagem `job.status != "queued"`, mas não há cancelamento cooperativo das etapas em execução. O integrador deve introduzir sinal/token de cancelamento, verificações entre chunks/etapas e limpeza somente após o worker parar, inclusive nos caminhos de cache/conversão/transcrição. Isso não foi alterado nesta entrega, por restrição de escopo.

### Acessibilidade e aparência

- Barra com `role="progressbar"`, rótulo, intervalo 0–100, valor atual ou indeterminado e descrição da etapa.
- Etapa ativa com `aria-current="step"`; `aria-busy` no botão de gerar durante o pedido.
- Mensagens normais em região `status` e erros em região `alert`, ambas atômicas. Mensagens idênticas não são reescritas a cada polling.
- Rótulos explícitos para texto/link; controle de expansão aponta para o texto; correção do teclado no botão de remover arquivo evita abrir o seletor junto.
- Mantidas as classes, CSS, paleta e estrutura visual existentes. Botão/aviso de cancelamento só aparecem durante pedido conhecido.

### EPUB

- `.epub` acrescentado ao seletor e EPUB às descrições da interface.
- Opções de páginas continuam exclusivas de PDF; seleção de EPUB limpa páginas antigas.
- **Requer integração do parser pelo responsável pelo backend antes da publicação.** O frontend não interpreta EPUB e o backend clonado ainda pode rejeitá-lo.

### Service worker

- Cache do shell atualizado para `supertonic-shell-v3`.
- Limpeza restrita aos caches `supertonic-shell-*`, preservando outros caches da mesma origem.
- Não guarda respostas HTTP falhas e usa `waitUntil` para persistência do cache.
- API e áudio continuam fora do cache do service worker.

## Validação executada

- Node `v20.19.5`: **18/18 testes passaram**, zero dependências npm.
- Chromium `152.0.7977.82`: **6/6 cenários passaram** com HTTP simulado, sem erros JavaScript capturados.
- `node --check static/app.js`: passou.
- `node --check static/sw.js`: passou.
- `git diff --check`: passou.
- Viewports 400 px e 1280 px sem overflow horizontal de página; screenshot de conclusão em `tests/results/desktop.png`.
- Logs completos: `tests/results/node-tests.txt` e `tests/results/chromium-tests.txt`.

Cobertura inclui intervalos adaptativos, backoff/Retry-After, suspensão oculta/offline, abortos e limpeza de listeners/timers, timeout durante leitura do corpo, recuperação 503, erro permanente sem retries, áudio final sem novas consultas de estado, cache do SW, EPUB/limpeza de páginas, foco e player no cancelamento, DELETE não confirmado, histórico e ausência de anúncios de status repetidos.

**Limites da validação:** não executou modelo TTS, transcrição/download externo, backend real, parser EPUB nem autenticação em produção. Visibilidade foi simulada deterministicamente via `document.hidden` + evento `visibilitychange`; throttling real do sistema operacional e leitores de tela precisam de teste manual. Nenhum teste pretende provar cancelamento cooperativo do backend. Ao ocultar a aba, áudio já conhecido pode continuar até esgotar seus chunks; descoberta de novos chunks/final só retoma quando visível. Não foi prometida reprodução contínua ilimitada em segundo plano.

## Aplicar e reproduzir

O ZIP é uma entrega parcial, não um clone completo. Sobreponha seus três arquivos `static/` ao repositório compatível; preserve as demais alterações do integrador. `frontend.patch` contém as mesmas mudanças para revisão/aplicação alternativa, **não** para aplicar depois de já sobrepor os arquivos.

```sh
# Na raiz da entrega ou do repositório com os testes copiados:
node --check static/app.js
node --check static/sw.js
node --test tests/frontend.test.cjs

# Smoke em browser: preferencialmente após sobrepor ao clone completo,
# para carregar também CSS e demais assets que não mudaram.
# Requer Python, pacote playwright e Chromium instalado.
FRONTEND_ROOT=/caminho/do/repositorio CHROMIUM_PATH=/usr/bin/chromium \
  python3 tests/browser_smoke.py
```

Os testes Node extraem as funções reais de polling em VM, sem exportações/globais de teste no código de produção. O smoke executa o app inteiro em Chromium com rotas HTTP simuladas.
