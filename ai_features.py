"""AI features for SuperTonic: Executive Summary, NotebookLM-style Podcast, and Translation.

Works with:
1) OpenAI API / Groq API (when OPENAI_API_KEY or GROQ_API_KEY is configured) for human-grade quality.
2) Zero-dependency offline NLP fallback (extractive summarization, smart dialog structuring, rule-based) so it always works out of the box even without any API key.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from typing import List, Tuple

logger = logging.getLogger("supertonic.ai")


def _get_api_config() -> Tuple[str, str, str]:
    """Returns (api_key, base_url, default_model)."""
    key = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_KEY")
        or os.environ.get("GROQ_API_KEY")
        or ""
    ).strip()
    if not key:
        return "", "", ""
    if key.startswith("gsk_"):
        return key, "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"
    return key, "https://api.openai.com/v1", os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")


def _call_llm(prompt: str, system_prompt: str, max_tokens: int = 2000) -> str | None:
    api_key, base_url, model = _get_api_config()
    if not api_key:
        return None
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("Falha na chamada ao LLM (%s): %s", model, exc)
        return None


# ---------------------------------------------------------------------------
# 1. Resumo Executivo
# ---------------------------------------------------------------------------
def summarize_text(text: str, max_length: int = 1500) -> str:
    """Gera um resumo executivo fluido do documento para ser narrado."""
    if not text or len(text) < 300:
        return text

    # Tenta LLM
    sys = (
        "Você é um especialista em síntese de documentos para áudio e audiolivros em português do Brasil. "
        "Crie um resumo executivo claro, envolvente e direto dos pontos principais do documento. "
        "O texto gerado será falado em voz alta por um narrador, portanto escreva frases naturais, sem tópicos ou asteriscos."
    )
    prompt = f"Faça um resumo executivo falado do seguinte texto:\n\n{text[:12000]}"
    llm_res = _call_llm(prompt, sys, max_tokens=1000)
    if llm_res:
        return llm_res

    # Fallback algorítmico sem API key (extractive summarization)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) <= 6:
        return text

    words = re.findall(r"\b[a-zA-ZáéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]{3,}\b", text.lower())
    stopwords = {
        "que", "para", "com", "não", "uma", "por", "mais", "dos", "como", "mas",
        "foi", "ele", "das", "tem", "seu", "sua", "este", "esse", "isso", "pela",
        "pelo", "são", "sobre", "foram", "também", "entre", "quando", "muito",
    }
    filtered = [w for w in words if w not in stopwords]
    freq = Counter(filtered)

    scores = []
    for i, s in enumerate(sentences):
        s_words = re.findall(r"\b[a-zA-ZáéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]{3,}\b", s.lower())
        score = sum(freq.get(w, 0) for w in s_words) / max(1, len(s_words))
        if i == 0:
            score *= 1.8
        scores.append((score, i, s))

    # Seleciona até 6 frases mais importantes
    target_count = min(8, max(4, len(sentences) // 4))
    top = sorted(sorted(scores, key=lambda x: x[0], reverse=True)[:target_count], key=lambda x: x[1])
    resumo_frases = [s for _, _, s in top]

    intro = "Resumo dos pontos principais do documento: "
    return intro + " ".join(resumo_frases)


# ---------------------------------------------------------------------------
# 2. Modo Podcast / Debate com 2 Vozes (Estilo NotebookLM)
# ---------------------------------------------------------------------------
STYLES_MAP = {
    "fun": "Estilo DESCONTRAÍDO & CURIOSO: conversa dinâmica, informal, bem-humorada e cativante, com perguntas provocativas.",
    "biz": "Estilo EXECUTIVO & NEGÓCIOS: foco estrito em métricas, ROI, eficiência, tomada de decisão e visão estratégica de mercado.",
    "edu": "Estilo AULA DIDÁTICA: tom pedagógico acolhedor, com analogias claras, explicações passo a passo como em uma aula memorável.",
    "debate": "Estilo DEBATE CRÍTICO: [Mulher 1] defende com entusiasmo as teses do documento, enquanto [Homem 1] pondera com questionamentos céticos realistas.",
}


def generate_podcast_script(text: str, style: str = "fun") -> str:
    """Gera um roteiro de podcast dinâmico com 2 apresentadores: [Mulher 1] e [Homem 1]."""
    if not text:
        return ""

    style_desc = STYLES_MAP.get(style, STYLES_MAP["fun"])
    sys = (
        "Você é um produtor de podcasts premiado no estilo do Google NotebookLM. "
        "Sua tarefa é transformar o documento enviado em um episódio de podcast fluido e conversacional "
        "entre dois apresentadores brasileiros muito carismáticos: [Mulher 1] e [Homem 1].\n\n"
        f"{style_desc}\n\n"
        "Regras estritas:\n"
        "1. Toda fala deve começar EXATAMENTE com '[Mulher 1]: ' ou '[Homem 1]: '.\n"
        "2. Eles devem conversar naturalmente, reagir um ao outro, fazer perguntas e explicar os pontos mais fascinantes do documento.\n"
        "3. Não use tópicos, emojis, notas de música ou indicações de palco (como risos ou suspiros), apenas o texto falado.\n"
        "4. Duração: cerca de 6 a 12 trocas de diálogo.\n"
        "5. O idioma é Português do Brasil coloquial e inteligente."
    )
    prompt = f"Transforme este documento em um diálogo de podcast empolgante entre [Mulher 1] e [Homem 1]:\n\n{text[:12000]}"
    llm_res = _call_llm(prompt, sys, max_tokens=1500)
    if llm_res and ("[Mulher 1]:" in llm_res or "[Homem 1]:" in llm_res):
        return llm_res

    # Fallback algorítmico sem API key
    summary = summarize_text(text, max_length=1200)
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    dialogue = []
    dialogue.append("[Mulher 1]: Olá! Bem-vindos a mais uma análise rápida em áudio. Hoje temos um conteúdo muito interessante para discutir.")
    dialogue.append("[Homem 1]: Com certeza! Vamos direto ao assunto. O que mais chama atenção neste material?")

    spk = "Mulher 1"
    for i, s in enumerate(sentences):
        if not s.strip():
            continue
        if spk == "Mulher 1":
            dialogue.append(f"[Mulher 1]: {s.strip()}")
            spk = "Homem 1"
        else:
            transicoes = [
                "E isso é fundamental porque ",
                "Outro ponto relevante que vale destacar é que ",
                "Exatamente, e além disso, ",
                "Perfeito! Vale notar também que ",
            ]
            t = transicoes[i % len(transicoes)]
            dialogue.append(f"[Homem 1]: {t}{s.strip().lower()}")
            spk = "Mulher 1"

    dialogue.append("[Mulher 1]: Excelente resumo. Esse foi o panorama essencial deste documento.")
    dialogue.append("[Homem 1]: Obrigado pela companhia de sempre e até a próxima!")
    return "\n\n".join(dialogue)


def generate_podcast_jingle(sample_rate: int = 24000, is_intro: bool = True):
    """Gera uma vinheta acústica harmônica e suave em float32 para o modo podcast."""
    import numpy as np

    duration = 2.2 if is_intro else 1.8
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    freqs = [261.63, 329.63, 392.00, 523.25] if is_intro else [523.25, 392.00, 329.63, 261.63]
    audio = np.zeros_like(t)
    for i, f in enumerate(freqs):
        delay = i * 0.14
        t_shifted = np.maximum(0, t - delay)
        env = np.exp(-t_shifted * 2.5) * (t >= delay)
        tone = np.sin(2 * np.pi * f * t_shifted) + 0.25 * np.sin(2 * np.pi * (f * 2) * t_shifted)
        audio += tone * env * 0.18
    fade_in = np.minimum(1.0, t / 0.05)
    fade_out = np.minimum(1.0, (duration - t) / 0.6)
    return (audio * fade_in * fade_out).astype(np.float32)


def build_podcast_rss_feed(items: list[dict], base_url: str) -> str:
    """Gera feed RSS 2.0 compatível com Apple Podcasts / Pocket Casts / Spotify."""
    from datetime import datetime, timezone
    import xml.etree.ElementTree as ET

    base = base_url.rstrip("/")
    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
    })
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "SuperTonic — Meus Documentos & Podcasts"
    ET.SubElement(channel, "link").text = base
    ET.SubElement(channel, "language").text = "pt-br"
    ET.SubElement(channel, "description").text = "Feed pessoal privado de documentos, audiolivros e podcasts gerados pelo SuperTonic."
    ET.SubElement(channel, "itunes:author").text = "SuperTonic"
    ET.SubElement(channel, "itunes:image", {"href": f"{base}/static/icon-512.png"})
    cat = ET.SubElement(channel, "itunes:category", {"text": "Technology"})
    ET.SubElement(cat, "itunes:category", {"text": "Podcasts"})

    for it in items:
        item = ET.SubElement(channel, "item")
        title = it.get("title") or "Documento em Áudio"
        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "description").text = it.get("preview") or "Áudio gerado no SuperTonic"
        guid = it.get("job_uuid") or it.get("id") or "doc"
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = str(guid)

        audio_url = f"{base}{it.get('audio_url')}" if it.get("audio_url", "").startswith("/") else it.get("audio_url", "")
        fmt = it.get("format", "mp3")
        mime = "audio/mp4" if fmt == "m4b" else ("audio/wav" if fmt == "wav" else "audio/mpeg")
        ET.SubElement(item, "enclosure", {
            "url": audio_url,
            "length": "1048576",
            "type": mime,
        })
        pub = it.get("created_at")
        if pub:
            try:
                dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
                ET.SubElement(item, "pubDate").text = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
            except Exception:
                ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        else:
            ET.SubElement(item, "pubDate").text = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    return ET.tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")


def parse_podcast_script(script: str, default_voice: str = "F1") -> List[Tuple[str, str]]:
    """Analisa o roteiro e divide em tuplas (voz, texto_para_falar)."""
    pattern = re.compile(
        r"^\s*\[?(Mulher(?:\s*\d+)?|Homem(?:\s*\d+)?|Apresentador\w*|Especialista\w*|F[1-5]|M[1-5])\]?\s*:\s*(.+)$",
        re.IGNORECASE,
    )
    lines = script.split("\n")
    chunks = []
    current_voice = default_voice
    male_voice = "M1" if default_voice.startswith("F") else "F1"

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            speaker_raw = m.group(1).lower()
            text = m.group(2).strip()
            if any(k in speaker_raw for k in ["homem", "m1", "m2", "m3", "m4", "m5", "especialista"]):
                voice = male_voice if default_voice.startswith("F") else default_voice
            else:
                voice = default_voice if default_voice.startswith("F") else "F1"
            chunks.append((voice, text))
        else:
            chunks.append((current_voice, line))

    return chunks if chunks else [(default_voice, script)]


# ---------------------------------------------------------------------------
# 3. Tradução Automática
# ---------------------------------------------------------------------------
def translate_to_portuguese(text: str) -> str:
    """Traduz documento em outro idioma para o português brasileiro."""
    if not text:
        return text

    sys = (
        "Você é um tradutor profissional especializado em verter documentos para o português do Brasil fluente, "
        "natural e adequado para narração em áudio. Mantenha os nomes próprios e termos técnicos consagrados."
    )
    prompt = f"Traduza o seguinte texto para português do Brasil:\n\n{text[:12000]}"
    llm_res = _call_llm(prompt, sys, max_tokens=2500)
    if llm_res:
        return llm_res
    return text
