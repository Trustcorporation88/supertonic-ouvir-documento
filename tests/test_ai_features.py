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


def test_translate_to_portuguese_fallback_offline():
    txt = "Hello world, this is a document."
    res = ai_features.translate_to_portuguese(txt)
    assert isinstance(res, str)
    assert len(res) > 0
