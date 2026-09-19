"""No TTS/server imports or model downloads; unittest and pytest compatible."""
import unittest
from unittest.mock import patch

import textnorm
from textnorm import normalize_for_tts, strip_repeated_lines


class TextNormalizationTests(unittest.TestCase):
    def test_brazilian_currency_does_not_match_only_first_three_digits(self):
        cases = {
            "R$1500,00": "mil e quinhentos reais",
            "R$ 1.500,00": "mil e quinhentos reais",
            "R$15000,01": "quinze mil reais e um centavo",
            "R$1,5": "um real e cinquenta centavos",
            "R$0,05": "zero reais e cinco centavos",
            "R$1.000.000,00": "um milhão de reais",
            "Total R$1500,00.": "Total mil e quinhentos reais.",
            "R$1500,00, pago.": "mil e quinhentos reais, pago.",
            "US$1500,20": "mil e quinhentos dólares e vinte centavos",
            "€1500,00": "mil e quinhentos euros",
            "R$1": "um real",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_for_tts(value), expected)

    def test_language_aliases(self):
        expected = normalize_for_tts("R$1500,00 e 30°C", "pt")
        for alias in ("pt-BR", "pt_br", "PT_BR", " pt-BR ", "pt-PT", "por", None):
            with self.subTest(alias=alias):
                self.assertEqual(normalize_for_tts("R$1500,00 e 30°C", alias), expected)
        self.assertEqual(normalize_for_tts("12 USD", "unknown"), "12 USD")
        self.assertEqual(normalize_for_tts("12", "en"), "twelve")

    def test_temperature_precedes_ordinals(self):
        cases = {
            "30°C": "trinta graus Celsius",
            "30º C": "trinta graus Celsius",
            "-1°C": "menos um grau Celsius",
            "+2,5 °F": "mais dois vírgula cinco graus Fahrenheit",
            "0°c": "zero graus Celsius",
            "1,0°C": "um vírgula zero grau Celsius",
            "12º e 3ª": "décimo segundo e terceira",
            "5º artigo e 35°C": "quinto artigo e trinta e cinco graus Celsius",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_for_tts(value), expected)

    def test_roman_only_in_explicit_structural_context(self):
        self.assertEqual(normalize_for_tts("Capítulo IV, Título IX e século XXI"),
                         "Capítulo quatro, Título nove e século vinte e um")
        self.assertEqual(normalize_for_tts("art. IV, inc. XIV"), "artigo quatro, inciso catorze")
        for text in ("CIVIL MIX CD IV", "João Paulo II", "capítulo IC", "capítulo IIII",
                     "modelo X", "capítulo iv", "capítulo IV-A", "xiv"):
            with self.subTest(text=text):
                self.assertEqual(normalize_for_tts(text), text)

    def test_legal_abbreviations_are_not_guessed(self):
        self.assertEqual(normalize_for_tts("art. 5º, inc. IV, §§ 2 e 3; fls. 12"),
                         "artigo quinto, inciso quatro, parágrafos dois e três; folhas doze")
        self.assertEqual(normalize_for_tts("inc. 2º"), "inciso segundo")
        self.assertEqual(normalize_for_tts("§1º e §§2 e 3"), "parágrafo primeiro e parágrafos dois e três")
        for text in ("Min. Silva", "seg. feira", "no. da ação", "inc. desconhecido",
                     "REsp ADI STF STJ CPC CC CF CLT", "artístico incidente",
                     "inc. CIVIL", "inc. IC", "inc. mix"):
            with self.subTest(text=text):
                self.assertEqual(normalize_for_tts(text), text)

    def test_existing_date_time_identifiers_and_units(self):
        self.assertEqual(normalize_for_tts("12/03/2026"), "doze de março de dois mil e vinte e seis")
        self.assertEqual(normalize_for_tts("14h30 e 35%"), "catorze horas e trinta e trinta e cinco por cento")
        self.assertEqual(normalize_for_tts("1500kg"), "mil e quinhentos quilos")
        self.assertEqual(normalize_for_tts("123.456.789-01"), "um dois três quatro cinco seis sete oito nove zero um")

    def test_optional_num2words_unavailable_keeps_numbers(self):
        with patch.object(textnorm, "_n2w", None):
            self.assertEqual(normalize_for_tts("R$1500,00 e 30°C"), "1500 reais e 30 graus Celsius")


class EdgeCleaningTests(unittest.TestCase):
    def test_repeated_headers_removed_only_at_outer_edge(self):
        pages = [f"Cabeçalho\nIntrodução {i}\n123\nTexto {i}\nRodapé" for i in range(3)]
        result = strip_repeated_lines(pages)
        for i, page in enumerate(result):
            self.assertEqual(page, f"Introdução {i}\n123\nTexto {i}")

    def test_body_match_protects_the_same_line_at_edge(self):
        pages = [f"Refrão\nIntrodução {i}\nRefrão\nTexto {i}\nFim {i}" for i in range(3)]
        self.assertEqual(strip_repeated_lines(pages), pages)

    def test_numbers_in_body_and_edges_are_preserved(self):
        pages = [f"2026\nAlfa {i}\n42\nBeta {i}\n{i + 1}" for i in range(3)]
        self.assertEqual(strip_repeated_lines(pages), pages)

    def test_explicit_page_label_only_removed_at_edge(self):
        page = "Página 1\nAlfa\nPágina 2\nBeta\nPágina 3"
        self.assertEqual(strip_repeated_lines([page]), ["Alfa\nPágina 2\nBeta"])

    def test_short_pages_and_empty_pages_preserved(self):
        pages = ["Cabeçalho\n123", "", "Cabeçalho\n123", "Cabeçalho\n123"]
        self.assertEqual(strip_repeated_lines(pages), pages)
        self.assertEqual(strip_repeated_lines([]), [])

    def test_no_accidental_second_line_header_removal(self):
        pages = [f"Título {i}\nCláusula importante\nDetalhe {i}\nOutro {i}\nFinal {i}" for i in range(3)]
        self.assertEqual(strip_repeated_lines(pages), pages)


if __name__ == "__main__":
    unittest.main()
