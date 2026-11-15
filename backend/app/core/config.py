"""Configuração central do Corpo Sano, lida exclusivamente de variáveis de ambiente.

Nenhum segredo fica no código-fonte: chaves, senhas e tokens vêm do ambiente
(arquivo .env fora do controle de versão ou secrets do servidor).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_MARKERS = ("change-me", "trocar", "exemplo", "example")


class Settings(BaseSettings):
    # CORPOSANO_ENV_FILE permite apontar o arquivo de configuração (instalação local no Windows)
    model_config = SettingsConfigDict(env_file=os.environ.get("CORPOSANO_ENV_FILE", ".env"),
                                      env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Corpo Sano"
    # local = instalação no computador da clínica (instalador Windows), acesso pela rede interna
    environment: Literal["development", "homologation", "production", "test", "local"] = "development"
    debug: bool = False
    version: str = "1.0.0"

    database_url: str = Field(..., description="postgresql+psycopg://usuario:senha@host:5432/banco")
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Segurança
    secret_key: str = Field(..., min_length=32, description="Chave de assinatura dos tokens JWT")
    encryption_keys: str = Field(..., description="Chaves Fernet (separadas por vírgula) para credenciais e arquivos")
    health_encryption_keys: str = Field(..., description="Chaves Fernet exclusivas para dados de saúde/anamnese")
    backup_encryption_key: str = Field(..., description="Chave AES-256 (base64, 32 bytes) para backups")
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    refresh_cookie_name: str = "cs_refresh"
    cookie_secure: bool = True
    cors_origins: str = ""
    trusted_proxies: str = "127.0.0.1,::1,172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"
    login_max_attempts: int = 5
    login_lock_minutes: int = 15
    rate_limit_per_minute: int = 300
    login_rate_limit_per_minute: int = 10
    password_min_length: int = 10

    # Aplicação
    public_base_url: str = "http://localhost:8080"
    timezone: str = "America/Sao_Paulo"
    storage_dir: str = "./data/files"
    max_upload_mb: int = 15

    # Backups
    backup_dir: str = "./data/backups"
    backup_retention_days: int = 30
    backup_daily_hour: int = 3
    pg_dump_path: str = "pg_dump"
    pg_restore_path: str = "pg_restore"
    backup_s3_endpoint: str = ""
    backup_s3_region: str = ""
    backup_s3_bucket: str = ""
    backup_s3_access_key: str = ""
    backup_s3_secret_key: str = ""
    backup_s3_prefix: str = "corpo-sano/"

    # Cópia adicional dos backups (ex.: HD externo ou pasta sincronizada com a nuvem)
    backup_mirror_dir: str = ""

    # Worker
    worker_interval_seconds: int = 30

    # Instalação local (servidor único que também entrega a interface)
    serve_frontend_dir: str = ""
    local_host: str = "0.0.0.0"
    local_port: int = 8080

    # Primeiro acesso (usado apenas se não existir nenhum usuário)
    initial_admin_email: str = ""
    initial_admin_password: str = ""
    initial_admin_name: str = "Administrador"

    @property
    def is_production(self) -> bool:
        return self.environment in ("production", "local")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if not self.sqlalchemy_url.startswith("postgresql"):
            raise ValueError("O Corpo Sano exige PostgreSQL como banco de dados (DATABASE_URL).")
        if self.environment in ("production", "homologation", "local"):
            for name in ("secret_key", "encryption_keys", "health_encryption_keys", "backup_encryption_key"):
                value = getattr(self, name).lower()
                if any(m in value for m in INSECURE_MARKERS):
                    raise ValueError(f"{name.upper()} contém valor de exemplo; gere uma chave real.")
        if self.environment in ("production", "homologation"):
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE deve ser true fora do ambiente de desenvolvimento.")
            if not self.public_base_url.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL deve usar HTTPS em homologação/produção.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
