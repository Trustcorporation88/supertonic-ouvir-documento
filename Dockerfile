FROM python:3.12-slim

# ffmpeg só é necessário para transcrição (aba Vídeo / arquivos de mídia).
ARG WITH_TRANSCRIBE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    $( [ "$WITH_TRANSCRIBE" = "1" ] && echo ffmpeg ) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-transcribe.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_TRANSCRIBE" = "1" ]; then pip install --no-cache-dir -r requirements-transcribe.txt; fi

ENV HF_HOME=/data/hf \
    PYTHONUNBUFFERED=1 \
    SUPERSONIC_MODEL=supertonic-3 \
    DEFAULT_LANG=pt

COPY start.sh server.py ./
COPY static ./static
RUN sed -i 's/\r$//' start.sh server.py && chmod +x start.sh

EXPOSE 8080
CMD ["bash", "./start.sh"]
