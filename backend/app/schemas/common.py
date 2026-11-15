from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.core.utils import is_valid_cnpj, is_valid_cpf, normalize_phone, only_digits

# Valores monetários: Decimal no backend, número no JSON
Money = Annotated[Decimal, PlainSerializer(lambda v: float(v) if v is not None else None, return_type=float | None, when_used="json")]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2), PlainSerializer(float, return_type=float, when_used="json")]
NonNegMoney = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2), PlainSerializer(float, return_type=float, when_used="json")]

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str
    data: Any = None


def clean_cpf(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    d = only_digits(v)
    if not is_valid_cpf(d):
        raise ValueError("CPF inválido.")
    return d


def clean_cnpj(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    d = only_digits(v)
    if not is_valid_cnpj(d):
        raise ValueError("CNPJ inválido.")
    return d


def clean_document(v: str | None) -> str | None:
    """CPF ou CNPJ."""
    if v is None or not str(v).strip():
        return None
    d = only_digits(v)
    if len(d) == 11:
        return clean_cpf(d)
    if len(d) == 14:
        return clean_cnpj(d)
    raise ValueError("Documento deve ser CPF (11 dígitos) ou CNPJ (14 dígitos).")


def clean_phone(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    return normalize_phone(v)


def clean_cep(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    d = only_digits(v)
    if len(d) != 8:
        raise ValueError("CEP deve ter 8 dígitos.")
    return d


def clean_uf(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    v = v.strip().upper()
    ufs = {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR",
        "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
    }
    if v not in ufs:
        raise ValueError("UF inválida.")
    return v


def clean_ibge(v: str | None) -> str | None:
    if v is None or not str(v).strip():
        return None
    d = only_digits(v)
    if len(d) != 7:
        raise ValueError("Código IBGE do município deve ter 7 dígitos.")
    return d


def empty_to_none(v: Any) -> Any:
    if isinstance(v, str) and not v.strip():
        return None
    return v.strip() if isinstance(v, str) else v


# Tipos reutilizáveis com validação
CpfStr = Annotated[str | None, AfterValidator(clean_cpf)]
CnpjStr = Annotated[str | None, AfterValidator(clean_cnpj)]
DocumentStr = Annotated[str | None, AfterValidator(clean_document)]
PhoneStr = Annotated[str | None, AfterValidator(clean_phone)]
CepStr = Annotated[str | None, AfterValidator(clean_cep)]
UfStr = Annotated[str | None, AfterValidator(clean_uf)]
IbgeStr = Annotated[str | None, AfterValidator(clean_ibge)]
ColorStr = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class StrippedModel(BaseModel):
    """Converte strings vazias em None e remove espaços."""

    @field_validator("*", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return empty_to_none(v)
