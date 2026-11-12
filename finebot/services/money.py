import re
from decimal import Decimal, ROUND_HALF_UP

MAX_CENTS = 1_000_000_000 * 100  # 1 billion


def parse_amount(text: str) -> int | None:
    """
    '50' / '50.5' / '1,250.75' / '50 birr'  ->  cents (int).
    Returns None for anything that is not a positive number
    (letters, negative, NaN, Infinity, zero, too big).
    """
    t = (text or "").strip().lower().replace(",", "").replace(" ", "")
    for suffix in ("birr", "etb", "br"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    if not t or len(t) > 15 or not re.fullmatch(r"\d+(\.\d+)?|\.\d+", t):
        return None
    cents = int((Decimal(t).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) * 100)
    if cents <= 0 or cents > MAX_CENTS:
        return None
    return cents


def fmt(cents: int) -> str:
    """12050 -> '120.50', 12000 -> '120', 123456700 -> '1,234,567'"""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    s = f"{whole:,}"
    return f"{sign}{s}" if frac == 0 else f"{sign}{s}.{frac:02d}"
