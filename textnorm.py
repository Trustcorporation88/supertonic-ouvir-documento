"""Normalização de texto para TTS (foco em pt-BR), limpeza de PDF e divisão em blocos.

O modelo lê "R$ 1.500,00", "12/03/2026", "Dr.", "14h30", "35%" de forma literal e
tropeça. Aqui expandimos para palavras antes de sintetizar. O texto exibido ao
usuário continua sendo o original limpo — só o que vai para a voz muda.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

try:
    from num2words import num2words as _n2w
except Exception:  # pragma: no cover
    _n2w = None

_LANG_MAP = {"pt": "pt_BR", "en": "en", "es": "es", "fr": "fr", "it": "it", "de": "de"}

MONTHS_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

ABBR_PT = {
    "dr.": "doutor", "dra.": "doutora", "sr.": "senhor", "sra.": "senhora", "srta.": "senhorita",
    "prof.": "professor", "profa.": "professora", "eng.": "engenheiro",
    "exmo.": "excelentíssimo", "exma.": "excelentíssima", "ilmo.": "ilustríssimo", "ilma.": "ilustríssima",
    "av.": "avenida", "tel.": "telefone", "cel.": "celular", "ltda.": "limitada", "cia.": "companhia",
    "nº": "número", "n.º": "número", "num.": "número",
    "art.": "artigo", "arts.": "artigos", "§§": "parágrafos", "§": "parágrafo",
    "pág.": "página", "págs.": "páginas", "pp.": "páginas", "cap.": "capítulo",
    "fig.": "figura", "tab.": "tabela", "ref.": "referência", "obs.": "observação",
    "aprox.": "aproximadamente", "p.ex.": "por exemplo", "etc.": "etcétera",
    "vs.": "versus", "máx.": "máximo", "mín.": "mínimo",
    "séc.": "século", "a.c.": "antes de Cristo", "d.c.": "depois de Cristo",
    "cnpj": "C N P J", "cpf": "C P F", "cep": "C E P",
    "pdf": "P D F", "url": "U R L", "html": "H T M L", "api": "A P I",
}

UNITS_PT = {
    "km": ("quilômetro", "quilômetros"), "m": ("metro", "metros"), "cm": ("centímetro", "centímetros"),
    "mm": ("milímetro", "milímetros"), "kg": ("quilo", "quilos"), "g": ("grama", "gramas"),
    "mg": ("miligrama", "miligramas"), "l": ("litro", "litros"), "ml": ("mililitro", "mililitros"),
    "km/h": ("quilômetro por hora", "quilômetros por hora"), "m²": ("metro quadrado", "metros quadrados"),
    "km²": ("quilômetro quadrado", "quilômetros quadrados"), "ha": ("hectare", "hectares"),
    "mb": ("megabyte", "megabytes"), "gb": ("gigabyte", "gigabytes"), "kb": ("kilobyte", "kilobytes"),
    "°c": ("grau Celsius", "graus Celsius"),
}


def _num(n, lang: str = "pt", **kw) -> str:
    if _n2w is None:
        return str(n)
    try:
        return _n2w(n, lang=_LANG_MAP.get(lang, "en"), **kw)
    except Exception:
        return str(n)


def _int_br(s: str) -> int:
    return int(re.sub(r"[.\s]", "", s))


def _decimal_pt(intpart: str, frac: Optional[str] = None) -> str:
    out = _num(_int_br(intpart))
    if frac:
        if frac.startswith("0") and len(frac) > 1:
            out += " vírgula " + " ".join(_num(int(d)) for d in frac)
        else:
            out += " vírgula " + _num(int(frac))
    return out


def _ordinal_pt(n: int, fem: bool) -> str:
    w = _num(n, to="ordinal")
    if fem:
        w = re.sub(r"o\b", "a", w)
    return w


# ---------------------------------------------------------------------------
# Limpeza estrutural
# ---------------------------------------------------------------------------
_URL = re.compile(r"(https?://|www\.)\S+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(?=[a-záéíóúãõçà])")
_SOFT_BREAK = re.compile(r"(?<![.!?:;\n])\n(?!\n)")
_PAGE_NUM = re.compile(r"^\s*(p[áa]g(ina|\.)?\s*)?\d{1,4}(\s*(de|/|-)\s*\d{1,4})?\s*$", re.I)


def clean_layout(text: str) -> str:
    """Corrige quebras de linha de PDF e espaços. Mantém parágrafos (linha dupla)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").replace("\u00ad", "")
    text = _HYPHEN_BREAK.sub(r"\1", text)
    text = _SOFT_BREAK.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^[•●▪■◦‣*]\s*", "", text, flags=re.M)
    return text.strip()


def strip_repeated_lines(pages: List[str], min_pages: int = 3) -> List[str]:
    """Remove boilerplate only at actual page edges, never matching body lines.

    Bare numbers are deliberately preserved: a value, year or chapter number
    cannot reliably be distinguished from a page number without PDF geometry.
    Short pages (fewer than five nonempty lines) are preserved in their entirety.
    Repeated candidates that also occur in any page body are preserved.
    """
    def key(line: str) -> str:
        return re.sub(r"\s+", " ", line.strip().casefold())

    split = [page.split("\n") for page in pages]
    indices = [[i for i, line in enumerate(lines) if line.strip()] for lines in split]
    counter: Counter = Counter()
    body_keys = set()
    for lines, idx in zip(split, indices):
        if len(idx) < 5:
            body_keys.update(key(lines[i]) for i in idx)
            continue
        body_keys.update(key(lines[i]) for i in idx[1:-1])
        counter.update({key(lines[idx[0]]), key(lines[idx[-1]])})
    threshold = max(3, min_pages, (len(pages) + 1) // 2)
    repeated = {k for k, count in counter.items()
                if count >= threshold and 0 < len(k) < 120
                and k not in body_keys and not _PAGE_NUM.fullmatch(k)}
    explicit_page = re.compile(r"^p[áa]g(?:ina|\.)?\s*\d{1,4}(?:\s*(?:de|/)\s*\d{1,4})?$", re.I)
    result = []
    for lines, idx in zip(split, indices):
        remove = set()
        if len(idx) >= 5:
            for i in (idx[0], idx[-1]):
                if key(lines[i]) in repeated or explicit_page.fullmatch(lines[i].strip()):
                    remove.add(i)
        result.append("\n".join(line for i, line in enumerate(lines) if i not in remove))
    return result


# ---------------------------------------------------------------------------
# Normalização para a voz
# ---------------------------------------------------------------------------
_CUR = {"R$": ("real", "reais"), "US$": ("dólar", "dólares"), "U$": ("dólar", "dólares"),
        "€": ("euro", "euros"), "£": ("libra", "libras")}


# Roman numerals are read only after explicit structural labels. Never replace
# isolated tokens (mix, civil, CD, names, product identifiers, party acronyms).
_ROMAN_CANONICAL = re.compile(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _roman_value(token: str) -> Optional[int]:
    if not token or not _ROMAN_CANONICAL.fullmatch(token):
        return None
    return sum(-_ROMAN_VALUES[c] if i + 1 < len(token) and _ROMAN_VALUES[c] < _ROMAN_VALUES[token[i + 1]]
               else _ROMAN_VALUES[c] for i, c in enumerate(token))


def _legal_and_roman_pt(text: str) -> str:
    # Ambiguous abbreviations expand only before a legal reference, not globally.
    legal = {"inc.": "inciso", "incs.": "incisos", "fl.": "folha", "fls.": "folhas"}
    pattern = r"(?<!\w)(inc\.|incs\.|fl\.|fls\.)(\s+)(\d+[ºª°]?|[IVXLCDM]+)(?!\w)"
    def legal_reference(match):
        token = match[3]
        if not token[0].isdigit() and _roman_value(token) is None:
            return match[0]
        return legal[match[1].lower()] + match[2] + token
    text = re.sub(pattern, legal_reference, text, flags=re.I)
    text = re.sub(r"§{1,2}", lambda m: " parágrafos " if len(m[0]) == 2 else " parágrafo ", text)
    # No expansion of 'no.', 'Min.', 'seg.', legal acronyms or citations into
    # guessed meanings. Paragraph symbols are unambiguous, including §1º.
    labels = r"(?i:capítulo|cap\.|título|livro|parte|seção|secção|inciso|incisos|artigo|art\.|século|séc\.)"
    pattern = rf"(?<!\w)({labels})(\s+)([IVXLCDM]+)(?![\w-])"
    def roman(match):
        n = _roman_value(match[3])
        return match[0] if n is None else match[1] + match[2] + _num(n)
    return re.sub(pattern, roman, text)


def _norm_pt(t: str) -> str:
    t = _URL.sub(" link ", t)
    t = _EMAIL.sub(" e-mail ", t)

    def money(m):
        cur, intp, frac = m.group(1), m.group(2), m.group(3)
        sing, plur = _CUR.get(cur.upper().replace(" ", ""), ("real", "reais"))
        n = _int_br(intp)
        connector = " de " if n >= 1_000_000 and n % 1_000_000 == 0 else " "
        out = f"{_num(n)}{connector}{sing if n == 1 else plur}"
        if frac and int(frac) > 0:
            c = int(frac.ljust(2, "0"))
            out += f" e {_num(c)} {'centavo' if c == 1 else 'centavos'}"
        return out

    t = re.sub(r"(?<!\w)(R\$|US\$|U\$|€|£)\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(?!\d|[.,]\d)", money, t)

    def pct(m):
        v = m.group(1)
        return (_decimal_pt(*v.split(",")) if "," in v else _num(int(v))) + " por cento"

    t = re.sub(r"(\d+(?:,\d+)?)\s?%", pct, t)

    def date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return m.group(0)
        if len(y) == 2:
            y = ("20" if int(y) < 50 else "19") + y
        dd = "primeiro" if d == 1 else _num(d)
        return f"{dd} de {MONTHS_PT[mo - 1]} de {_num(int(y))}"

    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b", date, t)

    def hour(m):
        h, mi = int(m.group(1)), m.group(2)
        if h > 23 or (mi and int(mi) > 59):
            return m.group(0)
        out = f"{_num(h)} {'hora' if h == 1 else 'horas'}"
        if mi and int(mi) > 0:
            out += f" e {_num(int(mi))}"
        return out

    t = re.sub(r"\b(\d{1,2})h(\d{2})?\b", hour, t)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b(?!:)", hour, t)

    # Temperature has priority over the ordinal-looking degree character.
    def temperature(m):
        sign, integer, fraction, scale = m.groups()
        value = _decimal_pt(integer, fraction)
        if sign == "-":
            value = "menos " + value
        elif sign == "+":
            value = "mais " + value
        one = int(integer) == 1 and not (fraction and int(fraction))
        return f"{value} {'grau' if one else 'graus'} {'Celsius' if scale.upper() == 'C' else 'Fahrenheit'}"

    t = re.sub(r"(?<![\w.,])([+-]?)(\d+)(?:,(\d+))?\s*[°º]\s*([CF])\b", temperature, t, flags=re.I)
    t = _legal_and_roman_pt(t)
    t = re.sub(r"\b(\d+)\s?([ºª°])(?!\s*[CF]\b)", lambda m: _ordinal_pt(int(m.group(1)), m.group(2) == "ª"), t)

    def unit(m):
        numtxt, u = m.group(1), m.group(2).lower()
        if u not in UNITS_PT:
            return m.group(0)
        sing, plur = UNITS_PT[u]
        if "," in numtxt:
            return f"{_decimal_pt(*numtxt.split(','))} {plur}"
        n = _int_br(numtxt)
        return f"{_num(n)} {sing if n == 1 else plur}"

    t = re.sub(r"\b((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?)\s?(km/h|km²|m²|[a-zA-Z]{1,2})\b", unit, t)

    def digits(m):
        return " ".join(_num(int(d)) for d in re.sub(r"\D", "", m.group(0)))

    t = re.sub(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", digits, t)                 # CPF
    t = re.sub(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", digits, t)           # CNPJ
    t = re.sub(r"\(?\b\d{2}\)?\s?\d{4,5}-\d{4}\b", digits, t)               # telefone
    t = re.sub(r"\b\d{5}-\d{3}\b", digits, t)                               # CEP

    def number(m):
        s = m.group(0)
        return _decimal_pt(*s.split(",")) if "," in s else _num(_int_br(s))

    t = re.sub(r"\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b", number, t)
    t = re.sub(r"\b\d+,\d+\b", number, t)
    t = re.sub(r"\b\d{1,15}\b", lambda m: _num(int(m.group(0))), t)

    def abbr(m):
        w = m.group(0)
        rep = ABBR_PT.get(w.lower())
        if rep is None:
            return w
        return rep.capitalize() if w[0].isupper() and not rep.isupper() else rep

    keys = sorted(ABBR_PT.keys(), key=len, reverse=True)
    t = re.sub(r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)", abbr, t, flags=re.I)

    t = t.replace("&", " e ").replace(" + ", " mais ").replace(" = ", " igual a ")
    t = re.sub(r"[\"“”«»]", "", t)
    t = re.sub(r"[_*#|>~^]", " ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _norm_generic(t: str, lang: str) -> str:
    t = _URL.sub(" link ", t)
    t = _EMAIL.sub(" email ", t)
    if lang == "en":
        t = re.sub(r"(\d+)\s?%", lambda m: _num(int(m.group(1)), lang) + " percent", t)
        t = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", lambda m: _num(int(m.group(0).replace(",", "")), lang), t)
    t = re.sub(r"\b\d{1,15}\b", lambda m: _num(int(m.group(0)), lang), t)
    t = re.sub(r"[\"“”«»_*#|>~^]", " ", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def normalize_for_tts(text: str, lang: Optional[str] = "pt") -> str:
    lang = (lang or "pt").strip().lower().replace("_", "-")
    if lang in {"pt-br", "pt-pt", "por"}:
        lang = "pt"
    if lang == "pt":
        return _norm_pt(text)
    if lang in _LANG_MAP:
        return _norm_generic(text, lang)
    return text


# ---------------------------------------------------------------------------
# Divisão em blocos para síntese progressiva
# ---------------------------------------------------------------------------
_SENT_SPLIT = re.compile(r"(?<=[.!?…;:])\s+(?=\S)")


def split_chunks(text: str, first: int = 110, size: int = 380, hard: int = 900) -> List[str]:
    """Divide o texto em blocos por frases. O primeiro é menor (áudio começa rápido).

    Os blocos concatenados reproduzem exatamente o texto original (com ``\\n\\n``
    entre parágrafos), para o cliente destacar o trecho em reprodução.
    """
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    pieces: List[str] = []
    for i, p in enumerate(paragraphs):
        parts = [s for s in _SENT_SPLIT.split(p) if s.strip()]
        for j, s in enumerate(parts):
            while len(s) > hard:
                cut = max(s.rfind(", ", 0, hard), s.rfind(" ", 0, hard))
                if cut < hard // 2:
                    cut = hard
                pieces.append(s[:cut] + " ")
                s = s[cut:].lstrip()
            last_in_par = j == len(parts) - 1
            last_par = i == len(paragraphs) - 1
            pieces.append(s + ("" if last_in_par and last_par else "\n\n" if last_in_par else " "))

    chunks: List[str] = []
    cur = ""
    limit = first
    for s in pieces:
        if cur and len(cur) + len(s) > limit:
            chunks.append(cur)
            cur = ""
            limit = size
        cur += s
        if s.endswith("\n\n"):  # fim de parágrafo sempre fecha o bloco (pausa + destaque por parágrafo)
            chunks.append(cur)
            cur = ""
            limit = size
    if cur.strip():
        chunks.append(cur)
    return chunks


def smart_skip_filter(text: str) -> str:
    """Limpeza inteligente estilo Speechify: remove números de páginas soltos,
    notas de rodapé numéricas tipo [1], separadores de tabela e linhas de rodapé."""
    if not text:
        return ""
    # Remove números de página isolados
    text = re.sub(r"(?mi)^\s*(?:p[aá]g(?:ina|\.)?\s*\d+(?:\s*(?:de|/)\s*\d+)?|\d+|- \d+ -)\s*$", "", text)
    # Remove referências de notas [1], [24]
    text = re.sub(r"\[(?:\d{1,3}|nota\s*\d+)\]", "", text)
    # Remove divisores de tabela e linhas de rodapé
    text = re.sub(r"(?m)^[\s\|\+\-\:\=]{4,}$", "", text)
    text = re.sub(r"(?m)^[_\-*]{3,}\s*$", "", text)
    # Compacta linhas vazias
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
