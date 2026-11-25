"""Utilidades compartidas de normalización de texto sin acentos y filtro de datos privados."""
import re
import unicodedata

PRIVATE_RE = re.compile(
    r"\d[\d \-.]{5,}\d|contraseñ|password|clave|pin\b|tarjeta|cuenta bancaria|dni|pasaporte|cvv|iban\b|api[ _-]?key",
    re.I,
)


def plain(s: str, *, collapse_spaces: bool = True) -> str:
    """Convierte a minúsculas y elimina marcas diacríticas ('Tímida' → 'timida')."""
    norm = unicodedata.normalize("NFD", str(s or "").strip().lower())
    clean = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", clean) if collapse_spaces else clean


def is_private_fact(text: str) -> bool:
    """¿Parece contener contraseñas, números largos (tarjetas/DNI/teléfonos) o claves?"""
    return bool(PRIVATE_RE.search(text or ""))
