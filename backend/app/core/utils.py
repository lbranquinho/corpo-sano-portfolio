"""Validações e utilitários brasileiros (CPF, CNPJ, telefone) e de datas."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.core.config import get_settings

CENT = Decimal("0.01")


def only_digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_text(value: str | None) -> str:
    """Minúsculas e sem acentos (para pesquisa)."""
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


LIKE_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Faz % e _ digitados pelo usuário valerem como texto comum num LIKE/ILIKE.
    Use junto com escape=LIKE_ESCAPE na consulta."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_contains(value: str) -> str:
    """Padrão 'contém' seguro para LIKE/ILIKE (usar com escape=LIKE_ESCAPE)."""
    return f"%{escape_like(value)}%"


def is_valid_cpf(value: str | None) -> bool:
    cpf = only_digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        total = sum(int(cpf[n]) * ((i + 1) - n) for n in range(i))
        digit = (total * 10 % 11) % 10
        if digit != int(cpf[i]):
            return False
    return True


def is_valid_cnpj(value: str | None) -> bool:
    cnpj = only_digits(value)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6] + weights1
    for weights, pos in ((weights1, 12), (weights2, 13)):
        total = sum(int(cnpj[i]) * w for i, w in enumerate(weights))
        rest = total % 11
        digit = 0 if rest < 2 else 11 - rest
        if digit != int(cnpj[pos]):
            return False
    return True


def normalize_phone(value: str | None) -> str | None:
    """Telefone brasileiro em formato E.164 sem '+' (ex.: 5511987654321)."""
    digits = only_digits(value)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 13:
        raise ValueError("Telefone inválido: informe DDD + número.")
    return digits


def phone_variants(digits: str) -> set[str]:
    """Números brasileiros podem chegar com ou sem o 9º dígito (WhatsApp)."""
    out = {digits}
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        out.add(digits[:4] + digits[5:])
    if digits.startswith("55") and len(digits) == 12:
        out.add(digits[:4] + "9" + digits[4:])
    return out


def money(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def split_installments(total: Decimal, count: int) -> list[Decimal]:
    total = money(total)
    base = (total / count).quantize(CENT, rounding=ROUND_HALF_UP)
    parts = [base] * count
    parts[-1] = total - base * (count - 1)
    return parts


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clinic_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)


def local_now() -> datetime:
    return datetime.now(clinic_tz())


def local_today() -> date:
    return local_now().date()


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(clinic_tz())


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """Início e fim (exclusivo) de um dia no fuso da clínica."""
    tz = clinic_tz()
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    from datetime import timedelta

    return start, start + timedelta(days=1)


def add_months(d: date, months: int) -> date:
    import calendar

    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def month_bounds(period: str) -> tuple[date, date]:
    """'AAAA-MM' -> (primeiro dia, último dia)."""
    import calendar

    year, month = (int(p) for p in period.split("-"))
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
