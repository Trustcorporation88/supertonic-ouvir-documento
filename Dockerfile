FROM python:3.12-slim

# WITH_TRANSCRIBE=1 habilita transcrição (ffmpeg + faster-whisper + yt-dlp)
# e OCR de imagens (tesseract por/eng + pytesseract).
ARG WITH_TRANSCRIBE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    $( [ "$WITH_TRANSCRIBE" = "1" ] && echo ffmpeg tesseract-ocr tesseract-ocr-por tesseract-ocr-eng ) \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-transcribe.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$WITH_TRANSCRIBE" = "1" ]; then pip install --no-cache-dir -r requirements-transcribe.txt; fi

ENV HF_HOME=/data/hf \
    PYTHONUNBUFFERED=1 \
    SUPERSONIC_MODEL=supertonic-3 \
    DEFAULT_LANG=pt \
    TESSERACT_LANG=por+eng

COPY start.sh server.py ./
COPY static ./static
RUN sed -i 's/\r$//' start.sh server.py && chmod +x start.sh

EXPOSE 8080
CMD ["bash", "./start.sh"]
