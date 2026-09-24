"""
Utilidades de sanitización y seguridad transversales a la aplicación.
"""

from typing import Any

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_formula_injection(val: Any) -> Any:
    """
    Sanitiza strings para prevenir CSV / Excel Formula Injection (CWE-1236).
    Si un valor comienza con =, +, -, @, \\t o \\r, se antepone un apóstrofe (')
    para forzar a los lectores de hojas de cálculo a interpretarlo como texto plano.
    """
    if val is None:
        return val
    if isinstance(val, (int, float, bool)):
        return val
    s = str(val)
    if not s:
        return s
    if s[0] in FORMULA_PREFIXES:
        return f"'{s}"
    return s


def sanitize_row(row: list | tuple) -> list:
    """Sanitiza todas las celdas de una fila para exportación CSV o Excel."""
    return [sanitize_formula_injection(c) for c in row]
