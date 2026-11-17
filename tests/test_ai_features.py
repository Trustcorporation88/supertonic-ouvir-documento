import ai_features


def test_summarize_text_short_unchanged():
    short = "Texto muito curto para resumir."
    assert ai_features.summarize_text(short) == short


def test_summarize_text_long_extractive():
    doc = """
    A inteligência artificial avançou significativamente nos últimos anos em todo o mundo.
    Modelos de linguagem modernos conseguem resumir relatórios e estruturar dados complexos com precisão.
    As empresas estão aplicando automação inteligente para acelerar o atendimento ao cliente e suporte.
    Pesquisadores ressaltam que a segurança da informação e a privacidade devem ser prioridades absolutas.
    Muitas diretrizes éticas foram estabelecidas por organizações internacionais para garantir o uso responsável.
    O impacto na produtividade corporativa tem sido amplamente documentado em diversos setores da economia.
    Por fim, a colaboração contínua entre humanos e sistemas inteligentes desenha o futuro do trabalho.
    """
    summary = ai_features.summarize_text(doc)
    assert len(summary) > 0
    assert len(summary) < len(doc)


def test_generate_and_parse_podcast_script():
    doc = """
    Este é um relatório sobre o desempenho financeiro da empresa no terceiro trimestre.
    O faturamento cresceu 28% em comparação ao mesmo período do ano anterior.
    A expansão para novos mercados foi o principal motor desse resultado positivo.
    Os custos operacionais foram reduzidos com o uso de novas ferramentas de automação.
    A perspectiva para o encerramento do ano permanece bastante otimista.
    """
    script = ai_features.generate_podcast_script(doc)
    assert "[Mulher 1]:" in script
    assert "[Homem 1]:" in script

    parsed = ai_features.parse_podcast_script(script, default_voice="F1")
    assert len(parsed) >= 2
    voices = {v for v, _ in parsed}
    assert "F1" in voices
    assert "M1" in voices


def test_translate_to_portuguese_fallback_offline(monkeypatch):
    import pytest
    monkeypatch.setattr(ai_features, '_call_llm', lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="Tradução indisponível"):
        ai_features.translate_to_portuguese("Hello world, this is a document.")



def test_podcast_rss_feed_generation():
    import ai_features
    sample_items = [
        {
            "job_uuid": "11111111-2222-3333-4444-555555555555",
            "title": "Episódio 1: Relatório Anual",
            "preview": "Visão geral sobre o desempenho da empresa",
            "created_at": "2026-09-20T10:00:00Z",
            "format": "mp3",
            "audio_url": "/api/documents/11111111-2222-3333-4444-555555555555/audio",
        }
    ]
    xml = ai_features.build_podcast_rss_feed(sample_items, "https://trustvoice.trustcorp.com.br")
    assert "<rss" in xml
    assert "<itunes:author>TrustVoice (Trust Corporation)</itunes:author>" in xml
    assert "Episódio 1: Relatório Anual" in xml
    assert "https://trustvoice.trustcorp.com.br/api/documents/11111111-2222-3333-4444-555555555555/audio" in xml


def test_podcast_styles_script_generation():
    import ai_features
    doc = "A tecnologia quântica promete revolucionar a criptografia e o processamento de dados nas próximas décadas."
    for style in ["fun", "biz", "edu", "debate"]:
        script = ai_features.generate_podcast_script(doc, style=style)
        assert "[Mulher 1]:" in script
        assert "[Homem 1]:" in script


def test_podcast_acoustic_jingles():
    import ai_features
    intro = ai_features.generate_podcast_jingle(24000, is_intro=True)
    outro = ai_features.generate_podcast_jingle(24000, is_intro=False)
    assert len(intro) > 0
    assert len(outro) > 0
    assert max(abs(intro)) <= 1.0
    assert max(abs(outro)) <= 1.0


class _Resp:
    def __init__(self, payload):
        self.payload = payload
    def read(self):
        import json
        return json.dumps(self.payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_anthropic_used_first_and_picks_newest_sonnet(monkeypatch):
    import json
    import ai_features
    ai_features._anthropic_model_cache.clear()
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-test')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-openai-bad')
    monkeypatch.delenv('ANTHROPIC_MODEL', raising=False)
    calls = []
    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        assert req.get_header('X-api-key') == 'sk-ant-test'
        if req.full_url.startswith('https://api.anthropic.com/v1/models'):
            return _Resp({'data': [{'id': 'claude-haiku-9'}, {'id': 'claude-sonnet-9'}, {'id': 'claude-sonnet-8'}]})
        body = json.loads(req.data)
        assert body['model'] == 'claude-sonnet-9' and body['system'] == 'SYS'
        return _Resp({'content': [{'type': 'text', 'text': 'Olá do Claude'}]})
    monkeypatch.setattr(ai_features.urllib.request, 'urlopen', fake_urlopen)
    assert ai_features._call_llm('oi', 'SYS', 100) == 'Olá do Claude'
    assert ai_features.llm_provider() == 'anthropic'
    assert all('openai.com' not in c for c in calls)


def test_anthropic_failure_falls_back_to_offline(monkeypatch):
    import ai_features
    ai_features._anthropic_model_cache.clear()
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-bad')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_KEY', raising=False)
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    def boom(req, timeout=0):
        raise OSError('network down')
    monkeypatch.setattr(ai_features.urllib.request, 'urlopen', boom)
    assert ai_features._call_llm('oi', 'SYS') is None
    script = ai_features.generate_podcast_script('Texto curto. Outra frase importante aqui.')
    assert '[Mulher 1]:' in script
