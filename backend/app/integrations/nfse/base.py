"""Contrato do adaptador fiscal. Cada provedor (Nacional, municipal X...) implementa esta interface,
mantendo o restante do sistema independente do serviço fiscal utilizado."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderMessage:
    code: str | None
    message: str
    detail: str | None = None


@dataclass
class ProviderResult:
    ok: bool
    http_status: int | None = None
    access_key: str | None = None
    dps_id: str | None = None
    nfse_xml: bytes | None = None
    event_xml: bytes | None = None
    pdf: bytes | None = None
    errors: list[ProviderMessage] = field(default_factory=list)
    alerts: list[ProviderMessage] = field(default_factory=list)
    communication_failure: bool = False  # True = situação desconhecida (não confirmar nem rejeitar)
    raw_summary: dict = field(default_factory=dict)

    def error_text(self) -> str:
        return "; ".join(f"[{e.code}] {e.message}" + (f" — {e.detail}" if e.detail else "") for e in self.errors) or "Erro não detalhado"


class FiscalProvider(ABC):
    name: str

    @abstractmethod
    def emit(self, signed_dps: bytes) -> ProviderResult: ...

    @abstractmethod
    def get_nfse(self, access_key: str) -> ProviderResult: ...

    @abstractmethod
    def get_by_dps(self, dps_id: str) -> ProviderResult: ...

    @abstractmethod
    def register_event(self, access_key: str, signed_event: bytes) -> ProviderResult: ...

    @abstractmethod
    def list_events(self, access_key: str) -> ProviderResult: ...

    @abstractmethod
    def download_danfse(self, access_key: str) -> ProviderResult: ...
