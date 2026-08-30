"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_LATEX_MAP: dict[str, str] = {
    r"\\times": "×", r"\\div": "÷", r"\\pm": "±", r"\\mp": "∓",
    r"\\leq": "≤", r"\\geq": "≥", r"\\neq": "≠", r"\\approx": "≈",
    r"\\infty": "∞", r"\\sqrt": "√", r"\\cdot": "·", r"\\degree": "°",
    r"\\alpha": "α", r"\\beta": "β", r"\\gamma": "γ", r"\\delta": "δ",
    r"\\epsilon": "ε", r"\\theta": "θ", r"\\lambda": "λ", r"\\mu": "μ",
    r"\\pi": "π", r"\\sigma": "σ", r"\\phi": "φ", r"\\omega": "ω",
    r"\\Delta": "Δ", r"\\Sigma": "Σ", r"\\Omega": "Ω",
    r"\\in": "∈", r"\\notin": "∉", r"\\subset": "⊂", r"\\subseteq": "⊆",
    r"\\cup": "∪", r"\\cap": "∩", r"\\forall": "∀", r"\\exists": "∃",
    r"\\rightarrow": "→", r"\\leftarrow": "←", r"\\Rightarrow": "⇒",
    r"\\leftrightarrow": "↔",
}

_FRACTION_RE = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_SUP_RE = re.compile(r"\^\{?(-?\w+)\}?")
_SUB_RE = re.compile(r"_\{?(-?\w+)\}?")

_SUPERSCRIPT_MAP = str.maketrans("0123456789-+()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺⁽⁾ⁿ")
_SUBSCRIPT_MAP = str.maketrans("0123456789-+()", "₀₁₂₃₄₅₆₇₈₉₋₊₍₎")


def _latex_to_unicode(text: str) -> str:
    text = _FRACTION_RE.sub(lambda m: f"{m.group(1)}⁄{m.group(2)}", text)
    for pattern, repl in _LATEX_MAP.items():
        text = re.sub(pattern, repl, text)
    text = _SUP_RE.sub(lambda m: m.group(1).translate(_SUPERSCRIPT_MAP), text)
    text = _SUB_RE.sub(lambda m: m.group(1).translate(_SUBSCRIPT_MAP), text)
    return text


def clean_html(text: str | None) -> str:
    """Sanitize HTML+LaTeX-laden question/answer text into clean plain text.

    Strips HTML tags (br, li, table, p, style, script, a, iframe, img) and
    normalizes common LaTeX math macros to Unicode equivalents.
    """
    if not text:
        return ""
    text = _latex_to_unicode(text)
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "iframe"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("• ")
    cleaned = soup.get_text()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def safe_filename(name: str, max_len: int = 60) -> str:
    """Transliterate + strip a string down to a filesystem-safe filename."""
    from unidecode import unidecode

    name = unidecode(name or "quiz")
    name = re.sub(r"[^\w\-. ]", "", name).strip().replace(" ", "_")
    return (name or "quiz")[:max_len]
