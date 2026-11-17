"""Offline regressions. No credentials, external requests, or audio generation."""
import pytest
import ai_features as ai


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    for key in ('ANTHROPIC_API_KEY', 'CLAUDE_API_KEY', 'OPENAI_API_KEY', 'OPENAI_KEY', 'GROQ_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    def blocked(*args, **kwargs):
        raise AssertionError('Network forbidden in tests')
    monkeypatch.setattr(ai.urllib.request, 'urlopen', blocked)


def test_translation_covers_whole_long_document(monkeypatch):
    text = ('First paragraph. ' * 1000) + 'LAST SENTENCE'
    chunks = []
    def translate(prompt, system, max_tokens):
        chunk = prompt.split('\n\n', 1)[1]
        chunks.append(chunk)
        return 'Traduzido ' + str(len(chunks))
    monkeypatch.setattr(ai, '_call_llm', translate)
    result = ai.translate_to_portuguese(text)
    assert ''.join(chunks) == text
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert len(chunks) > 3
    assert result.endswith('Traduzido ' + str(len(chunks)))


def test_translation_without_provider_is_not_false_success():
    with pytest.raises(RuntimeError, match='Tradução indisponível'):
        ai.translate_to_portuguese('English source')
    assert ai.translate_to_portuguese('') == ''


def test_partial_translation_failure_is_not_returned(monkeypatch):
    results = iter(['Traduzido', None])
    monkeypatch.setattr(ai, '_call_llm', lambda *a, **k: next(results))
    with pytest.raises(RuntimeError, match='Tradução indisponível'):
        ai.translate_to_portuguese('word ' * 1000)


@pytest.mark.parametrize('text', ['short ' * 15, 'sentence long ' * 1000, 'Sentence here. ' * 300])
def test_summary_honors_length_in_every_offline_path(text):
    assert 0 < len(ai.summarize_text(text, max_length=65)) <= 65


def test_summary_bounds_provider_output(monkeypatch):
    monkeypatch.setattr(ai, '_call_llm', lambda *a, **k: 'Long generated summary. ' * 50)
    assert len(ai.summarize_text('Source text. ' * 40, max_length=100)) <= 100
    with pytest.raises(ValueError):
        ai.summarize_text('text', max_length=0)


def test_long_summary_ranks_sentences_beyond_first_12000(monkeypatch):
    monkeypatch.setattr(ai, '_call_llm', lambda *a, **k: pytest.fail('Must not send just a prefix'))
    text = (('a ' * 80) + '. ') * 100 + 'Quantum quantum quantum final finding.'
    assert 'final finding' in ai.summarize_text(text, max_length=1500)


def test_podcast_continuation_keeps_last_speaker():
    assert ai.parse_podcast_script('[Mulher 1]: First\n[Homem 1]: Second\nContinuation', 'F3') == [
        ('F3', 'First'), ('M1', 'Second'), ('M1', 'Continuation')]
    assert ai.parse_podcast_script('[Mulher 1]: First\nContinuation', 'M4') == [('F1', 'First'), ('F1', 'Continuation')]


def test_truncated_anthropic_output_rejected(monkeypatch):
    monkeypatch.setattr(ai, '_anthropic_model', lambda key: 'fake')
    monkeypatch.setattr(ai, '_http_json', lambda *a, **k: {'stop_reason': 'max_tokens', 'content': [{'type':'text','text':'partial'}]})
    with pytest.raises(RuntimeError, match='limite de tokens'):
        ai._call_anthropic('test-only', 'x', 'y', 10)


def test_truncated_openai_output_rejected(monkeypatch):
    monkeypatch.setattr(ai, '_get_api_config', lambda: ('fake', 'https://example.test', 'fake'))
    monkeypatch.setattr(ai, '_http_json', lambda *a, **k: {'choices': [{'finish_reason':'length','message':{'content':'partial'}}]})
    with pytest.raises(RuntimeError, match='limite de tokens'):
        ai._call_openai_compatible('x', 'y', 10)


def test_feed_date_converts_timezone():
    xml = ai.build_podcast_rss_feed([{'created_at': '2026-01-01T10:00:00-03:00', 'audio_url':'/audio'}], 'https://example.test')
    assert '13:00:00 +0000' in xml
