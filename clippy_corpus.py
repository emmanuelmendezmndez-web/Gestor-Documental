"""Comparación de frases para el entrenamiento y la revisión manual."""

import re
import unicodedata
from difflib import SequenceMatcher

LIMITE_SIMILITUD = 0.90


def normalizar(texto):
    plano = "".join(c for c in unicodedata.normalize("NFD", texto.casefold()) if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", plano))


def frases_cercanas(primera, segunda):
    comparador = SequenceMatcher(None, primera, segunda)
    return comparador.quick_ratio() >= LIMITE_SIMILITUD and comparador.ratio() >= LIMITE_SIMILITUD
