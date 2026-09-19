# Relatório de resultados — textnorm, EPUB e M4B

## Base e escopo

- Repositório: https://github.com/Trustcorporation88/supertonic-ouvir-documento
- Commit clonado: `74709583001b1122707d7df2e43aab54f048e9df` (clone raso).
- Execução: 19/09/2026 (UTC).
- Alterado: `textnorm.py`.
- Criados: `document_features.py`, dois arquivos de testes, documentação e evidências abaixo.
- **Não alterados:** `server.py`, `static/`, `requirements.txt`, `requirements-transcribe.txt`.
- Sem push, sem download de modelos TTS, sem importação de `server.py`/Supertonic, sem chamada a serviços externos de síntese.

## Resultado final reproduzível

| Verificação | Resultado |
|---|---|
| `python -m unittest discover -s tests -p 'test_*features.py' -v` | **44 testes, OK**, 0,248 s |
| `python -m pytest tests/test_textnorm_features.py tests/test_document_features.py -q` | **44 passed**, 0,36 s |
| Testes ignorados/skipped | **0** |
| `python -m py_compile textnorm.py document_features.py` | Aprovado |
| `git diff --check` | Aprovado |
| Diff em servidor, static e requirements | Vazio |

Tempos são da execução local e não constituem benchmark. Testes repetidos por unittest e pytest são os **mesmos 44 casos**, não 88 testes diferentes. Evidências completas: `docs/test-results/unittest-features.log`, `pytest-features.log` e `feature-junit.xml`.

## O que foi validado

### Normalização e preservação

- `R$1500,00`, milhares agrupados e não agrupados, centavos de um/dois dígitos, singular/plural, milhão, moedas estrangeiras, pontuação final.
- Aliases `pt-BR/pt_BR`, caixa/espaços, fallback sem num2words e preservação de idioma desconhecido.
- Temperatura Celsius/Fahrenheit, sinal, decimal, `º` e `°`, precedência sobre ordinais.
- Romanos somente em contexto estrutural; tokens isolados, nomes, formas inválidas e contexto jurídico ambíguo preservados.
- Referências jurídicas com números/ordinais/romanos e parágrafos adjacentes; sem expansão especulativa de siglas ou `Min./no./seg.`.
- Datas, horas, percentuais, CPF e unidades existentes.
- Cabeçalhos/rodapés repetidos apenas nas bordas reais; corpo, números, páginas curtas, páginas vazias e segunda linha preservados.

### EPUB

- Metadados, ordem do spine diferente da ordem ZIP/manifest, capítulos, texto inline, separação de parágrafos e offsets exatos.
- Nenhuma chamada a extract/extractall, rede ou gravação de conteúdo EPUB em disco.
- Limites de bytes compactados/descompactados, entradas, razão de compressão, texto e spine.
- Preflight do diretório central **antes** de construir `ZipFile`, inclusive contagem de entradas falsificada.
- Traversal absoluto/relativo, percent-encoding, backslash, symlink, entradas/IDs/spine duplicados, referências remotas.
- DTD/ENTITY em container, OPF e XHTML, inclusive UTF-16/32.
- CRC corrompido, compressão não suportada, flag de criptografia, membros ausentes, XML/ZIP inválido, documento sem texto.
- XHTML com 2.000 níveis sem recursão Python, headings ocultos e cauda fora do título.

### M4B

- Construção de argv sem shell; escape de metadados; ordenação/intervalos dos capítulos; validação de capa/timeout/saída.
- FFmpeg ausente, falha de processo, timeout, saída ausente/inválida e remoção de temporários.
- Destino preexistente, symlink e corrida de outro escritor não são sobrescritos.
- **Integração real:** PCM mono de silêncio de 1 segundo → AAC em M4B; tags com acentos, dois capítulos com tempos reais e capa PNG como attached picture; leitura de metadados e decodificação do áudio por FFmpeg.
- **Integração real sem capa/capítulos:** AAC válido, título presente e ausência de attached picture/capítulos.
- **Timeout real:** executável local de teste dormindo, terminado pelo limite de 0,1 s; sem publicação de destino nem diretório temporário restante.

## Ambiente

- Python 3.12.12, Linux x86_64 / glibc 2.41.
- `num2words` 0.5.14 (dependência já prevista no projeto).
- FFmpeg 7.0.2-static, binário **preinstalado** de `imageio_ffmpeg`; FFmpeg não estava no PATH.
- Nenhum pacote Python adicional instalado para esta entrega.

## Decisões e limitações explícitas

1. O módulo está pronto para integrar, mas **não foi conectado ao servidor/UI** nesta subentrega, conforme divisão de trabalho. Seguir `docs/document_features_integration.md` para pontos exatos de extração, exportação, MIME, cache e tempos de capítulos.
2. Leitura EPUB é estrita: rejeita DTD, ZIP64/multidisco, criptografia/ofuscação e XHTML malformado. Isto pode rejeitar livros legítimos; o comportamento é documentado e não tenta reparos inseguros silenciosos.
3. Um capítulo é um item linear XHTML do spine. Não interpreta completamente NCX, CSS, fórmulas, imagens, DRM nem layout fixo.
4. Limpeza de bordas continua heurística, embora mais conservadora. Números de página soltos são preservados de propósito.
5. M4B precisa de FFmpeg externo no ambiente de produção. A capa é um arquivo local opcional, não extraída automaticamente do EPUB. A publicação exige filesystem com hardlinks.
6. Tempos M4B precisam vir das amostras reais, incluindo pausas. O módulo valida intervalos, mas o chamador verifica duração total. Não foi feito teste em Apple Books/players móveis ou teste ponta a ponta do servidor integrado.
7. O objetivo é reduzir riscos e preservar conteúdo, não garantir interpretação jurídica ou detecção perfeita de boilerplate. Documento original deve permanecer disponível.
