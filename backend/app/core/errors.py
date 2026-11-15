from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Erro de regra de negócio com mensagem clara para o usuário."""

    status_code = 400

    def __init__(self, message: str, *, code: str = "erro_negocio", details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
        if status_code:
            self.status_code = status_code


class NotFound(AppError):
    status_code = 404

    def __init__(self, what: str = "Registro"):
        super().__init__(f"{what} não encontrado(a).", code="nao_encontrado")


class Conflict(AppError):
    status_code = 409

    def __init__(self, message: str, details: Any = None):
        super().__init__(message, code="conflito", details=details)


class Forbidden(AppError):
    status_code = 403

    def __init__(self, message: str = "Você não tem permissão para esta operação."):
        super().__init__(message, code="sem_permissao")


class IntegrationError(AppError):
    status_code = 502

    def __init__(self, message: str, details: Any = None):
        super().__init__(message, code="erro_integracao", details=details)
