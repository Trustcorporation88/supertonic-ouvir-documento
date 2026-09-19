# ROADMAP — leitura de documentos em áudio

Data da revisão documental: 19/09/2026.

## 1. Escopo e limites da comparação

**Este documento é uma comparação documental, não um benchmark executado.** Nenhum dos quatro concorrentes foi instalado, executado ou medido nesta tarefa. Não há resultado próprio de latência, qualidade de voz, consumo de RAM, alinhamento ou throughput. Não se conclui que um projeto seja mais rápido ou mais preciso do que outro.

A pesquisa utilizou exclusivamente resultados e snippets de **web search**, inclusive resultados indexados do GitHub. Não foi utilizado Web Fetch, scraping do GitHub, clonagem desses concorrentes ou integração GitHub. Nenhuma integração foi criada ou modificada.

Snippets podem ser resumidos pelo buscador, incompletos, desatualizados ou contraditórios. “Documentado” abaixo significa **corroborado pelo resultado de busca**, não confirmado por inspeção do código ou por teste funcional. Não foram fixados commits ou versões desses repositórios. Antes de incorporar código, conferir o arquivo LICENSE e as dependências na versão exata escolhida.

O histórico literal das alegações anteriores não estava disponível para esta revisão. A auditoria cobre as alegações correspondentes aos recursos solicitados — leitura sincronizada, formatos, exportação, podcast, SSML, timestamps, execução CPU e workers — sem atribuir retrospectivamente frases não recuperadas. As prioridades para `supertonic-ouvir-documento` são propostas, não afirmações de que o código atual já implementa ou deixa de implementar cada recurso.

### Legenda de evidência

- **D — documentado em busca:** resultado primário indexado descreve a funcionalidade.
- **P — parcial:** há suporte para parte da alegação, mas não para uma formulação mais ampla.
- **NV — não verificado:** evidência insuficiente; não equivale a afirmar ausência.
- **M — medido:** exigiria teste reproduzível. **Nenhum item desta revisão é M.**

## 2. Comparação dos upstreams

| Projeto upstream | Papel principal documentado | Recursos corroborados pelos snippets | Limites da conclusão |
|---|---|---|---|
| [richardr1126/openreader][1] | Aplicação de leitura e acompanhamento de texto | PDF, EPUB, TXT, Markdown e DOCX; múltiplos provedores TTS; acompanhamento por segmentos; destaque por palavra via alinhamento Whisper; exportação de audiolivros M4B/MP3 e capítulos retomáveis nos resultados do README [1][2] | Não é um engine TTS único. Precisão do alinhamento, custo e qualidade de leitura não foram testados. Recursos mudam conforme versão e provedor. |
| [remsky/Kokoro-FastAPI][3] | Servidor/API para Kokoro-82M | API de fala compatível com OpenAI; CPU e GPU; streaming; mistura de vozes; endpoints de fonemas; legendas/timestamps por palavra ou trecho; token de pausa `[pause:1.5s]` [3][4] | Compatibilidade com um endpoint não significa paridade integral com a API OpenAI. Timestamps documentados não provam alinhamento forçado independente. Tokens de pausa não são suporte geral a SSML. |
| [lamm-mit/PDF2Audio][6] | Transformação de PDFs em conteúdo falado com geração de roteiro | Múltiplos PDFs; templates de podcast, palestra e resumo; geração de texto e TTS com modelos OpenAI; vozes de diferentes falantes; revisão iterativa do texto; interface Gradio e chave OpenAI [6][7] | Podcast/resumo é transformação semântica, não leitura literal nem garantia de fidelidade. Não foi demonstrada operação totalmente local/offline, sem custos de API ou com alinhamento palavra a palavra. |
| [santinic/audiblez][8] | Conversão de e-books em audiolivros | EPUB para WAVs por capítulo e saída M4B com FFmpeg; Kokoro como sintetizador [8][9][10] | Não transferir recursos de forks para o upstream. Não foram demonstrados editor de podcast, leitura visual sincronizada ou desempenho superior no equipamento-alvo. |

**Identidade dos projetos:** resultados também mostram o nome histórico `OpenReader-WebUI` associado a `richardr1126/openreader`; não tratá-lo como um quinto concorrente independente. O upstream de audiblez considerado aqui é **santinic/audiblez**.

### Licenças: o que foi efetivamente corroborado

| Projeto | Licença indicada | Evidência e grau de confirmação |
|---|---|---|
| OpenReader | **MIT** | Resultados do repositório/README [1][2]. A consulta direcionada ao LICENSE não retornou um resultado útil nesta pesquisa; validação documental parcial, sem leitura integral do arquivo. |
| Kokoro-FastAPI | **Apache-2.0** | Resultado indexado do próprio arquivo LICENSE [5], além do README [4]. |
| PDF2Audio | **Apache-2.0** | Resultado do repositório [6] e metadados/README do Space oficial [7]. A consulta direcionada ao LICENSE não retornou resultado útil; não foi conferido o texto integral de licença no commit do GitHub. |
| audiblez | **MIT** | Resultado indexado do LICENSE upstream [11], corroborado pelos metadados PyPI [9]. |

**Separar sempre:** licença do aplicativo, licença dos pesos/modelos, licença de bibliotecas, licença da compilação do FFmpeg, termos do provedor e direitos sobre documentos/vozes. Resultados de Kokoro-FastAPI indicam pesos Kokoro-82M Apache-2.0 e código de inferência adaptado de StyleTTS2 MIT [4]; isso não substitui inventário de dependências. Não se infere que todos os modelos, vozes ou arquivos gerados sejam livres de restrições. O uso de APIs comerciais pode ter cobrança e termos próprios, mesmo com aplicativo permissivamente licenciado.

## 3. Auditoria das alegações de recursos

| Alegação | Classificação | Formulação defensável |
|---|---|---|
| “OpenReader acompanha cada palavra.” | D | Os resultados descrevem destaque por palavra usando alinhamento Whisper [1][2]. Não afirmar exatidão universal, custo desprezível ou ausência de processamento adicional. |
| “OpenReader lê PDF e EPUB e exporta M4B.” | D, com ressalva de versão | README indexado descreve esses recursos [2]. Um resultado do site variou a descrição dos formatos de exportação; usar a evidência do README como indicação, não contrato de versão. |
| “Kokoro-FastAPI fornece timestamps.” | D | Há endpoints de fala legendada com tempos por palavra/trecho [3][4]. Isso não comprova algoritmo, precisão ou equivalência a alinhamento forçado. |
| “Kokoro-FastAPI tem SSML completo.” | P; formulação ampla não sustentada | O README indexado distingue o token exato `[pause:1.5s]` de SSML e de sintaxes alternativas não reconhecidas [4]. Não promover pausa inline a conformidade SSML. |
| “PDF2Audio gera podcast com LLM.” | D | Templates e geração de roteiro com modelos OpenAI estão descritos [6][7]. Não confundir com narração literal; custos e revisão editorial precisam ser previstos. |
| “audiblez upstream converte EPUB para M4B.” | D | EPUB → WAVs por capítulo → M4B com FFmpeg é documentado [8][9][10]. |
| “Multi-workers acelera CPU por definição.” | NV | CPU suportada não comprova ganho ao multiplicar processos. Modelo por processo, RAM e competição entre threads exigem benchmark local. Não usar GPU como substituto de medição CPU. |
| “Tempo por palavra proporcional ao texto é alinhamento forçado.” | Não é equivalência técnica | Estimativa proporcional, timestamps do sintetizador e alinhamento forçado são métodos diferentes; a interface deve informar qual foi usado. |
| “Permissivo significa todos os componentes e conteúdos sem restrições.” | Não sustentada | As licenças indicadas são do projeto; dependências, pesos, APIs, vozes e documentos exigem análise separada. |

Resultados de issues de concorrência no Kokoro-FastAPI relatam dúvidas/crashes [12][13], mas são relatos de usuários, não benchmark controlado nem prova de defeito generalizado. Não serão utilizados como evidência de superioridade de outra solução ou como conclusão sobre GIL: bibliotecas nativas podem ter comportamento diferente do código Python puro.

## 4. Direção do produto e ordem de execução

Objetivo: oferecer leitura de documentos previsível, compreensível e recuperável, antes de ampliar formatos, semântica ou infraestrutura. Priorizar fidelidade do texto, reprodução básica, progresso real e tratamento de falhas. Não substituir o engine atual apenas porque outro projeto anuncia mais recursos.

Dependências: **P0 → P1 → P2**, com os itens caros de P3 sujeitos a gates próprios. Todos os critérios abaixo são **metas propostas**, não resultados de testes já aprovados.

### P0 — confiabilidade e transparência da interface

| Entrega | Critérios de aceite |
|---|---|
| Estados claros do trabalho | Mostrar fila, extração, síntese, finalização, concluído e erro apenas quando suportados por eventos reais. Se o backend não distinguir uma etapa, exibir estado genérico honesto. Não transformar um cronômetro em progresso factual. |
| Progresso verificável | Quando houver total conhecido, apresentar unidades concluídas/total. Caso contrário, estado indeterminado. Só apresentar 100% após conclusão real e saída disponível. Identificar ETA como estimativa ou omiti-la. |
| Reprodução e retomada local | Play/pause/seek e persistência da posição quando o áudio e a identidade do documento permitirem; recarregar a página não deve atribuir posição a outro documento. Mensagem explícita para áudio expirado ou indisponível. |
| Erros e acessibilidade | Falha de rede, falha de extração e síntese devem ter mensagens distintas quando houver informação disponível. Controles operáveis por teclado, foco visível e anúncio de estado acessível sem anunciar cada incremento. Texto vazio não deve iniciar geração. |
| Identidade visual da seleção | Voz, documento e opções selecionados devem ser legíveis antes de gerar e permanecer coerentes durante o job. Mudança de seleção não deve renomear retroativamente o áudio em execução. |

Aceite mínimo de P0: roteiro manual registrado em 400 px e desktop, navegação por teclado e cenários feliz/erro/recarga. Testes de interface não equivalem a benchmark TTS. Nenhuma alteração de integração é necessária para escrever ou aprovar este roadmap.

### P1 — texto, segmentação e recuperação

- **Extração e pré-visualização:** permitir conferir o texto antes da síntese; diferenciar PDF sem texto de texto efetivamente extraído. Não prometer OCR se ele não estiver implementado.
- **Segmentos estáveis:** preservar ordem e pontuação; evitar divisão no meio de palavras; manter identidade de segmento e associação com o áudio.
- **Falha parcial e retomada:** definir contrato de checkpoints; reutilizar segmentos válidos, invalidando cache quando texto, voz, engine, versão ou parâmetros relevantes mudarem.
- **Limites e limpeza:** documentar tamanho de entrada, duração/armazenamento e retenção; falhas não devem deixar arquivos temporários indefinidamente.

**Aceite:** fixtures com acentos PT-BR, parágrafos longos, títulos, listas, páginas vazias e PDF de múltiplas colunas; registrar limites conhecidos. Em um documento com segmentos conhecidos, uma falha simulada e retomada não pode omitir, duplicar ou reordenar segmentos concluídos. Se a retomada depender de novo suporte backend, tratá-la como entrega separada — não fingir persistência via interface.

### P2 — medição antes de otimização e sincronização básica

1. Implementar primeiro navegação/destaque **por segmento** quando houver correspondência real entre segmento e áudio.
2. Identificar explicitamente sincronização estimada; não usar rótulo “palavra exata” para interpolação.
3. Registrar tempos de extração, carregamento, síntese e montagem separadamente, preservando privacidade do documento.
4. Criar protocolo CPU reproduzível antes de propor multi-workers; um worker permanece baseline, não conclusão de ótimo universal.

**Aceite:** ao clicar um segmento com offset conhecido, reprodução e seleção apontam para o mesmo segmento; offsets monotônicos e dentro da duração do áudio. Métricas exportáveis devem incluir versão do app/engine/modelo, CPU, núcleos, RAM, threads, configuração e corpus. Publicar limitações junto dos números.

## 5. P3 — recursos caros explicitamente diferidos

| Recurso diferido | Por que não entra no caminho crítico | Gate e critérios de aceite para reconsiderar |
|---|---|---|
| **Podcast com LLM** | Nova dependência, custo por token, latência, envio de documentos e risco de inventar/omitir conteúdo. | Opt-in separado de “leitura literal”; orçamento e confirmação antes de API paga; roteiro revisável antes de TTS; indicar conteúdo transformado; referenciar trechos/páginas de origem quando disponíveis; corpus revisado por humano sem afirmações novas não sustentadas. Definir tratamento de privacidade e falhas. |
| **SSML suportado pelo engine** | Parser próprio não garante execução pelo sintetizador; dialetos e subconjuntos divergem. | Só habilitar tags efetivamente suportadas pela versão do engine. Publicar matriz de tags/atributos; testar pausa, prosódia ou pronúncia individualmente conforme suporte real; rejeitar ou avisar tags não suportadas; impedir entidades externas se houver XML. Tokens de pausa devem ser chamados de tokens, não SSML completo. |
| **Timestamps por palavra via alinhamento forçado** | Modelo/etapa adicional, custo CPU/RAM e erros em números, abreviações e pronúncias. | Escolher e licenciar alinhador; manter texto normalizado rastreável; medir erro em corpus PT-BR com referência anotada; tratar palavras omitidas e confiança baixa; apresentar fallback por segmento. Meta inicial proposta: erro absoluto mediano ≤200 ms e p95 ≤500 ms para fronteiras anotadas, com cobertura de palavras reportada; validar se adequado ao produto antes de assumir compromisso. Nunca aprovar apenas por observação visual. |
| **Multi-workers** | Pode duplicar modelos, aumentar RAM e piorar latência por competição com threads nativas. | **Somente após benchmark CPU no hardware-alvo.** Comparar 1/2/4 workers até o limite seguro de memória, com mesmo corpus e orçamento de threads. Gate proposto: ganho de throughput ≥20%, sem aumentar p95 de latência em mais de 10%, sem OOM/crashes e dentro do teto de RAM previamente definido. Se não passar, manter 1 worker. GPU não valida este gate. |
| **M4B e EPUB** | EPUB exige extração estrutural e segurança de arquivo; M4B envolve capítulos, metadados, codificação e compatibilidade de players. | Fase separada para entrada EPUB e saída M4B. EPUB: ordem de leitura baseada no spine, capítulos, Unicode, arquivos malformados, proteção contra zip bomb/path traversal e ausência de execução de conteúdo ativo. M4B: duração coerente, metadados/capítulos corretos, reprodução e busca verificadas em dois players definidos, sem duplicação ou truncamento; licença/configuração do FFmpeg revisadas. Não oferecer remoção de DRM. |

A existência desses recursos em concorrentes é inspiração documental, não justificativa suficiente para adicioná-los imediatamente nem promessa de compatibilidade com o engine atual.

## 6. Protocolo futuro de benchmark CPU

**Não executado nesta tarefa.**

- Fixar versões/commits, modelo, voz, sample rate, formato de saída, limites de segmento e flags de CPU.
- Registrar hardware/OS e manter serviços concorrentes controlados; separar download/carregamento de inferência.
- Corpus público ou autorizado em PT-BR com textos curtos, médios e longos; registrar caracteres, segmentos e duração produzida. Não publicar documentos privados.
- Medir execução fria e aquecida separadamente, com no mínimo três repetições por configuração; para p95 sob concorrência, usar quantidade suficiente de requisições e declarar tamanho amostral.
- Reportar tempo até primeiro áudio quando aplicável, tempo total, throughput em segundos de áudio gerados por segundo de parede, RAM pico, falhas, p50/p95 de latência e configuração de threads/workers.
- RTF = tempo de processamento / duração do áudio; menor é melhor. Não confundir com seu inverso, “vezes tempo real”. Indicar se inclui extração e montagem.
- Testar 1, 2 e 4 workers sob a mesma carga e limites de CPU/RAM; evitar oversubscription de threads. Interromper configurações que excedam memória.
- Comparações entre engines exigem explicar diferenças de vozes, qualidade e saídas: velocidade não substitui avaliação auditiva de fidelidade e inteligibilidade.

## 7. Checklist de liberação

- [ ] Definir baseline do produto e transformar metas aprovadas em tarefas pequenas.
- [ ] Confirmar licenças e versões exatas antes de copiar código ou empacotar dependências.
- [ ] Registrar testes funcionais P0 e P1, com evidências de sucesso e limitações.
- [ ] Não anunciar percentual, ETA, alinhamento ou suporte de formato que não tenha contrato/teste correspondente.
- [ ] Só publicar números de desempenho acompanhados do protocolo e resultados brutos.
- [ ] Manter podcast, SSML, alinhamento forçado, multi-workers e M4B/EPUB fora da entrega principal até seus gates.

## 8. Fontes da pesquisa

As URLs abaixo foram retornadas por web search. Foram usados **snippets**, não leitura integral via scraper; o acesso de pesquisa ocorreu em 19/09/2026. Links de README/LICENSE apontam a branches mutáveis. Data de indexação do buscador não é garantia de data de implementação.

[1]: https://github.com/richardr1126/openreader
[2]: https://github.com/richardr1126/openreader/blob/main/README.md
[3]: https://github.com/remsky/Kokoro-FastAPI
[4]: https://github.com/remsky/Kokoro-FastAPI/blob/master/README.md
[5]: https://github.com/remsky/Kokoro-FastAPI/blob/master/LICENSE
[6]: https://github.com/lamm-mit/PDF2Audio
[7]: https://huggingface.co/spaces/lamm-mit/PDF2Audio/blob/main/README.md
[8]: https://github.com/santinic/audiblez
[9]: https://pypi.org/project/audiblez/
[10]: https://github.com/santinic/audiblez/blob/main/README.md
[11]: https://github.com/santinic/audiblez/blob/main/LICENSE
[12]: https://github.com/remsky/Kokoro-FastAPI/issues/384
[13]: https://github.com/remsky/Kokoro-FastAPI/issues/261

1. [OpenReader upstream][1] e [README indexado][2]: formatos, acompanhamento, provedores, exportação e indicação MIT.
2. [Kokoro-FastAPI upstream][3], [README][4] e [LICENSE indexado][5]: CPU/GPU, API, captions, limites da sintaxe de pausa e Apache-2.0.
3. [PDF2Audio upstream][6] e [README do Space oficial][7]: geração de roteiro, TTS, Gradio, chave OpenAI e indicação Apache-2.0.
4. [audiblez upstream][8], [PyPI][9], [README][10] e [LICENSE indexado][11]: EPUB, capítulos WAV, M4B/FFmpeg e MIT.
5. [Issue sobre crashes de workers][12] e [discussão de concorrência][13]: contexto de risco; não evidência experimental comparativa.
