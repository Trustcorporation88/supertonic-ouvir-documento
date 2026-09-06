# SuperTonic — ouvir documento

Interface web + API para transformar **PDF, Word, texto, imagem, áudio ou vídeo** em áudio com vozes naturais,
usando o [Supertonic TTS](https://github.com/supertone-inc/supertonic) (ONNX, roda em CPU).

![screenshot](docs/screenshot.png)

## Recursos

- ⚡ **Começa a tocar em segundos** — o texto é dividido em blocos; o primeiro trecho toca enquanto o resto é gerado
- 📊 **Fila com progresso real** (`/api/jobs`) — sem conexões longas que estouram timeout; funciona com PDFs de 100 páginas e vídeos de 1 h
- 🎯 **Texto sincronizado** — o trecho em reprodução fica destacado; clique em qualquer parte para ouvir dali
- 🗣️ **Normalização pt-BR** antes da voz: `R$ 1.500,00` → "mil e quinhentos reais", datas, horas, `35%`, `1º`, `Dr.`, CPF/telefone dígito a dígito, unidades
- 🧹 **Limpeza de PDF** — remove cabeçalhos/rodapés repetidos, números de página e quebras de linha no meio da frase
- 🎧 **MP3** (64 kbps mono, ~10× menor que WAV) além de WAV/OGG/FLAC
- 💾 **Histórico persistente** no navegador (IndexedDB, últimos 20 áudios com texto)
- 🎤 **10 vozes** com prévia, velocidade 0.7×–2×, idioma; tema claro/escuro; PWA
- 📄 Lê **PDF, DOCX, TXT/MD/CSV/HTML, SRT/VTT**
- 🎬 **Transcreve áudio/vídeo e links** (YouTube, MP4…) — via **OpenAI** (`openai_key`, rápido) com fallback **faster-whisper** local; **OCR de imagens** com tesseract
- 🔐 API `/v1/*` compatível com OpenAI (`POST /v1/audio/speech`) protegida por `API_KEY`

## Rodando local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# opcional (vídeo/áudio/OCR): precisa de ffmpeg e tesseract-ocr no sistema
pip install -r requirements-transcribe.txt

cp .env.example .env   # edite API_KEY
export $(grep -v '^#' .env | xargs)
python server.py       # http://localhost:8080
```

Na primeira execução o modelo (~ centenas de MB) é baixado para `HF_HOME` (padrão `/data/hf`).

## Deploy no Railway

1. Crie um projeto a partir deste repositório (o `railway.toml` já aponta para o `Dockerfile`).
2. Em **Variables**, defina `API_KEY` (e, se quiser, `DEFAULT_LANG`, `MAX_UPLOAD_MB`…).
3. Monte um **Volume** em `/data` para não baixar o modelo a cada deploy.
4. Para habilitar transcrição e OCR, em **Variables** adicione `WITH_TRANSCRIBE=1` (o Railway repassa como build arg ao Dockerfile).

## Rotas

| Método | Rota | Auth | Descrição |
|---|---|---|---|
| GET | `/` | — | Interface web |
| GET | `/health` | — | `{"status": "ok"\|"loading"}` |
| GET | `/api/voices` | — | Vozes disponíveis |
| POST | `/api/jobs` | — | Cria um job. Form-data: `text` **ou** `file` **ou** `url`; `voice`, `lang`, `speed`, `response_format` (`mp3`/`wav`/`ogg`/`flac`). Responde `202` com `{"id", ...}`. |
| GET | `/api/jobs/{id}` | — | Progresso: `status`, `stage`, `percent`, `message`, `text`, `chunks[]`, `chunk_urls[]`, `audio_url`, `duration`. |
| GET | `/api/jobs/{id}/chunks/{n}` | — | WAV do bloco *n* (reprodução progressiva). |
| GET | `/api/jobs/{id}/audio` | — | Arquivo final. |
| POST | `/usar` | — | Rota síncrona legada (texto/arquivo → áudio com `X-Texto`; `url` → JSON `{"text"}`). |
| POST | `/v1/tts` | 🔑 | TTS nativo (JSON) |
| POST | `/v1/audio/speech` | 🔑 | Alias compatível com OpenAI |
| GET | `/docs` | — | Swagger |

```bash
curl -X POST https://SEU-APP.up.railway.app/v1/audio/speech \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"input":"Olá, mundo!","voice":"F1","lang":"pt","response_format":"wav"}' -o fala.wav
```

## Estrutura

```
server.py                  # FastAPI: UI, fila de jobs, /usar, /health, API key
textnorm.py                # normalização pt-BR, limpeza de PDF, divisão em blocos
static/                    # index.html · styles.css · app.js · PWA
requirements.txt           # supertonic[serve], pypdf, python-docx, num2words
requirements-transcribe.txt# faster-whisper + yt-dlp + pytesseract (opcional)
Dockerfile · start.sh · railway.toml
```

## Variáveis

| Nome | Padrão | Uso |
|---|---|---|
| `API_KEY` | — | Protege `/v1/*` |
| `openai_key` / `OPENAI_API_KEY` | — | Transcrição via OpenAI (`gpt-4o-mini-transcribe`); sem ela usa Whisper local |
| `WITH_TRANSCRIBE` | `0` | Build arg: instala ffmpeg, whisper, yt-dlp, tesseract |
| `DEFAULT_LANG` | `pt` | Idioma padrão |
| `MAX_UPLOAD_MB` / `MAX_TEXT_CHARS` | `200` / `120000` | Limites |
| `MP3_BITRATE` | `64k` | Qualidade do MP3 |
| `JOB_TTL_SECONDS` | `10800` | Tempo que os áudios ficam no servidor |

## Licença

MIT — o modelo Supertonic tem licença própria; veja o repositório oficial.
