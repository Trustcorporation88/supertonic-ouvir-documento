# Integração: normalização, EPUB e M4B

Base inspecionada: `74709583001b1122707d7df2e43aab54f048e9df`.
Este pacote **não altera** `server.py`, `static/`, `requirements.txt` nem outros requisitos. Não importa servidor/TTS nem baixa modelos. O integrador deve ligar explicitamente as APIs abaixo; copiar os arquivos, sozinho, não habilita EPUB/M4B na interface.

## Arquivos

- `textnorm.py`: substituição compatível com as assinaturas existentes.
- `document_features.py`: módulo independente, apenas biblioteca padrão Python (3.10+).
- `tests/test_textnorm_features.py`, `tests/test_document_features.py`: unittest/pytest.
- `docs/document_features_results.md`: evidências de execução e limitações.

## 1. Normalização

`normalize_for_tts(text, lang)` aceita `pt`, `pt-BR`, `pt_BR`, variações de caixa/espaços, `pt-PT` e `por`. Estes aliases usam o mesmo normalizador **brasileiro**; `pt-PT` não implementa pronúncia europeia distinta. Outros idiomas conservam o caminho existente.

- Moeda não captura apenas os primeiros três dígitos: `R$1500,00` → `mil e quinhentos reais`. Aceita milhar agrupado e pontuação final. Um dígito decimal é décimo de real: `R$1,5` → `um real e cinquenta centavos`.
- `30°C`, `30º C`, negativos e Fahrenheit são tratados **antes** dos ordinais. `5º` continua ordinal.
- Romanos canônicos em MAIÚSCULAS são convertidos somente após rótulos explícitos (`capítulo`, `cap.`, `título`, `livro`, `parte`, `seção`, `secção`, `inciso(s)`, `artigo`, `art.`, `século`, `séc.`). `CIVIL`, `CD`, `MIX`, nomes como `João Paulo II`, romanos minúsculos e formas inválidas ficam intactos fora desses contextos. Usa cardinais, sem adivinhar sentido legal/monárquico.
- `inc./incs./fl./fls.` expandem apenas antes de referência numérica/romana válida; `§/§§` funcionam mesmo adjacentes ao número. `Min.`, `seg.`, `no.` e siglas jurídicas não são expandidas globalmente: seus sentidos são ambíguos. Não há substituição automática de `CPC`, `CC`, `CF`, `ADI`, `REsp`, `STF` ou similares por interpretações presumidas.
- `strip_repeated_lines` remove repetição apenas na primeira/última linha não vazia de páginas com pelo menos cinco linhas. Nunca remove uma ocorrência no corpo; se o mesmo texto aparece no corpo de qualquer página, protege também as bordas. Preserva páginas curtas, números soltos (inclusive anos/valores/possíveis números de página) e a segunda/penúltima linha. Rótulos explícitos `Página 3` são removidos só nas bordas. Cabeçalhos repetidos ainda são uma **heurística**, não classificação semântica; preserve o documento original para auditoria. A nova política prefere deixar resíduos a apagar conteúdo.

O texto original de exibição deve continuar separado do texto normalizado para voz, como no servidor existente. `num2words` já está em `requirements.txt`; não foi adicionada dependência. A indisponibilidade opcional de `num2words` continua deixando os números em dígitos.

## 2. EPUB: contrato e ligação mínima

```python
from document_features import EpubError, extract_epub, read_epub

text = extract_epub(upload_bytes)  # adaptador -> str
book = read_epub(upload_bytes)     # EpubDocument completo
# book.title: str; book.author: str; book.text: str
# book.chapters: tuple[EpubChapter, ...]
# chapter.title, chapter.text, chapter.href, chapter.start_char, chapter.end_char
assert book.text[book.chapters[0].start_char:book.chapters[0].end_char] == book.chapters[0].text
```

No `server.py` da base, inserir em `_extract_from_upload` **antes** do ramo `TEXT_EXT`:

```python
if ext == ".epub":
    try:
        return extract_epub(data)
    except EpubError as exc:
        raise UsarError("EPUB inválido, protegido ou acima dos limites de segurança.",
                        422, "invalid_epub") from exc
```

Também anunciar `.epub` no formulário/accept e na lista de formatos suportados/ajuda. Não adicionar EPUB a `TEXT_EXT`: seus bytes são ZIP, não texto. Usar o limite de upload existente **antes** de acumular o arquivo em memória; o limite do módulo é defesa adicional.

Para capítulos/metadados, o adaptador acima descarta detalhes por design. Em `_run_job`, no ramo de arquivo EPUB, chamar `read_epub(data)` uma única vez, guardar `book`/seus campos no `Job` e usar `text = book.text`. Não chamar `clean_layout` posteriormente se os offsets forem usados. Ao truncar `MAX_TEXT_CHARS`, descartar capítulos totalmente fora do trecho e recortar o fim dos demais; não deixar offsets de texto que não será lido.

### Ordem e significado de capítulos

A ordem vem de `META-INF/container.xml` → pacote OPF → `spine`, nunca da ordem ZIP nem da ordem do `manifest`. Cada item XHTML não vazio e linear do spine vira um capítulo; não há subdivisão automática por todos os headings nem interpretação completa do NCX. O título usa primeiro heading visível `h1/h2/h3`, depois `<title>`, depois `Capítulo N`. Os itens `nav`, `linear="no"` e os tipos de spine não textuais são omitidos. Texto de script/style/nav/head/noscript/hidden/aria-hidden não é narrado. CSS não é avaliado; documentos só de imagens, EPUB DRM e layouts fixos sem texto legível não têm OCR neste módulo.

### Limites e segurança

`EpubLimits` permite configuração explícita pelo servidor (não exponha controles arbitrários ao cliente):

| Limite padrão | Valor |
|---|---:|
| Arquivo ZIP | 64 MiB |
| Entradas | 2.048 |
| Tamanho descomprimido por entrada | 8 MiB |
| Total descomprimido declarado | 128 MiB |
| Razão descomprimido/comprimido por entrada | 200 |
| Texto unido | 4.000.000 caracteres |
| Referências spine/capítulos | 1.024 |
| Elementos por documento XML | 100.000 |

O diretório central é validado e contado antes de instanciar `ZipFile`, evitando alocação ilimitada de objetos mesmo com contagem declarada falsificada. ZIP64 e multidisco são rejeitados (desnecessários dentro dos limites adotados). Todas as entradas são verificadas, inclusive imagens não usadas. Leituras são limitadas; CRC é verificado pelo `zipfile`. Não há `extract`/`extractall`, disco temporário para EPUB nem requisição de rede. Rejeita caminhos absolutos/traversal/backslash, referências remotas, duplicatas de nomes/IDs/documentos spine, symlinks, ZIP criptografado, compressões além de stored/deflate e `META-INF/encryption.xml` (inclui EPUBs com ofuscação de fontes). Referências relativas/percent-encoding são normalizadas sem escapar da raiz do arquivo.

XML é estrito; DTD/ENTITY são rejeitados também em UTF-16/32. Isso deliberadamente rejeita alguns EPUBs legítimos com DOCTYPE ou XHTML malformado. Não há execução de JavaScript, aplicação de CSS, fetch de imagens nem resolução de entidades. Estes limites não substituem limite de concorrência, memória e tempo do worker/processo: EPUB é processado de forma síncrona e não oferece cancelamento próprio. Para API async, executar em worker ou `asyncio.to_thread`, como os extratores existentes.

## 3. M4B: contrato e ligação mínima

```python
from document_features import AudioChapter, M4BError, M4BTimeoutError, export_m4b

path = export_m4b(
    audio_path,                       # WAV local já sintetizado, não upload arbitrário
    job.dir / "full.m4b",             # pai existe; arquivo de saída NÃO pode existir
    title="Título do livro",
    author="Autora",
    chapters=[AudioChapter("Capítulo 1", 0, 12_500),
              AudioChapter("Capítulo 2", 12_500, 25_000)],
    cover_path=None,                   # caminho local de JPEG/PNG opcional
    timeout=120,
    ffmpeg=FFMPEG,                     # caminho do executável já detectado pelo servidor
    metadata={"language": "por", "comment": "Gerado a partir do documento"},
)
```

`AudioChapter` recebe **milissegundos reais**, não caracteres. Intervalos precisam ser inteiros, positivos em duração, ordenados e sem sobreposição; início zero é válido. O chamador deve garantir que o último fim não ultrapasse a duração real do áudio — não há ffprobe extra no módulo. O timeout cobre o processo FFmpeg, não o tempo de leitura do EPUB ou a síntese TTS.

No servidor base:

1. Expor `m4b` em `OUTPUT_FORMATS` apenas quando FFmpeg estiver disponível. Disponibilidade do executável não garante suporte ao encoder AAC; falhas são reportadas.
2. No passo `# 4) arquivo final` de `_run_job`, inserir um ramo `elif fmt == "m4b"` **antes** de `encode_audio(full, sr, fmt)`. Escrever WAV usando `_wav_bytes(full, sr)`, chamar `export_m4b`, atribuir `job.final = str(path)` e apagar o WAV temporário em `finally`. Não passar `m4b` diretamente a `encode_audio` do Supertonic.
3. Para preservar capítulos reais, dividir o texto por capítulo antes de `split_chunks`, mantendo associação de cada chunk ao capítulo. Contabilizar amostras de `wav` **já com as pausas inseridas**. Para uma fronteira de amostra `s`, usar `round(s * 1000 / sr)`; usar a mesma fronteira como fim do anterior/início do próximo para evitar gaps ou sobreposição por arredondamento. Não derivar timestamps por proporção de caracteres ou pelo valor `dur` retornado pelo TTS. Colapsar capítulos vazios ou menores que 1 ms, se ocorrerem.
4. Sem esse rastreamento, exportar com `chapters=()` — o áudio M4B é válido, mas não anunciar capítulos de navegação.
5. Mapear M4B para MIME `audio/mp4` nas rotas de download, share, respostas síncronas e reprodução. Nome de download deve terminar em `.m4b`. O suporte do player web depende do navegador e não foi testado aqui; WAV dos chunks continua disponível.
6. Chamar exportação fora do event loop. Traduzir `M4BTimeoutError` para código estável (ex.: `m4b_timeout`) e `M4BError` para `m4b_export_failed`. Não devolver um WAV com extensão `.m4b` nem marcar job como concluído quando exportação falhar. Como o ramo trabalha com WAV temporário local, o servidor pode oferecer retry explícito em WAV, mas precisa alterar formato/nome/MIME corretamente.
7. Chave de cache deve incluir versão da normalização e, quando cachear o **arquivo final**, título, autor, capítulos reais, hash da capa e demais metadados. Como opção mais simples, reaproveitar apenas áudio base e executar o empacotamento de novo. Cache antigo não deve ocultar correções de `textnorm.py`.

### Segurança e comportamento do exportador

- O argumento `ffmpeg` deve ser controlado pelo servidor, nunca pelo usuário HTTP. Usar caminhos locais gerados por job; não permitir acesso a caminhos arbitrários recebidos do cliente.
- Sem shell. `-nostdin` evita bloqueio por interação. Protocolos dos inputs restritos a `file,pipe`.
- Encoder AAC 128 kbps e contêiner MP4/M4B com faststart. Tags `title`, `artist`, `album` vêm dos parâmetros `title`/`author`; `genre` é `Audiobook` e prevalece sobre metadata. Extras permitidos: `album`, `artist`, `title`, `genre`, `date`, `comment`, `copyright`, `description`, `language` (os quatro primeiros têm precedência dos parâmetros/valor fixo mencionados).
- Metadados são limitados a 16.384 caracteres por valor, sem NUL; newline é achatado e caracteres de controle de FFmetadata são escapados. Não há interpolação em comando shell.
- Capa opcional JPEG/PNG até 10 MiB, validada por assinatura e copiada como `attached_pic`. Não é extraída automaticamente do EPUB. Usar imagens confiáveis/validadas pelo servidor; não há reamostragem nem limite de dimensões de imagem neste módulo.
- FFmpeg timeout mata/aguarda o subprocesso via `subprocess.run`. Diretório temporário e saídas parciais são removidos em sucesso/erro/timeout. Erros não expõem stderr nem caminhos ao cliente.
- Saída é checada por existência, tamanho mínimo e marca MP4 `ftyp`; isto não substitui uma auditoria completa do áudio. Os testes reais também decodificam o áudio resultante.
- Publicação usa hardlink atômico no mesmo filesystem, sem sobrescrever destino existente nem vencedor de corrida. Usar filesystem que suporte hardlinks; saída em diretório local confiável. O módulo não cria diretórios finais nem substitui arquivos existentes.

## 4. Executar testes sem TTS

A partir da raiz do repositório:

```bash
python -m unittest discover -s tests -p 'test_*features.py' -v
python -m pytest tests/test_textnorm_features.py tests/test_document_features.py -q
python -m py_compile textnorm.py document_features.py
```

`num2words` deve estar instalado (dependência já existente); pytest só é necessário para o segundo comando. Não é necessário instalar/importar `supertonic`, iniciar `server.py`, acessar redes ou baixar modelos. Os testes FFmpeg reais usam executável no PATH ou binário **já instalado** de `imageio_ffmpeg`, sem chamar downloader; se nenhum estiver disponível, esses testes serão marcados como skip. Os demais testes de construção de comando, limpeza e timeout usam mocks/executável local de teste e continuam funcionando.

## Limites de validação desta entrega

Testes em Linux, fixtures sintéticas EPUB 2/3 estruturais e PCM de silêncio de 1 segundo. Não foi auditada uma biblioteca de EPUBs comerciais nem compatibilidade Apple Books/players móveis; tampouco houve teste ponta a ponta do servidor modificado pelo integrador. Sem download TTS, sem alterações em produção e sem push Git.
