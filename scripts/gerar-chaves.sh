#!/usr/bin/env bash
# Gera chaves aleatórias para o .env (SECRET_KEY, chaves Fernet e chave de backup) e a senha do banco.
# Uso: ./scripts/gerar-chaves.sh >> .env   (revise o arquivo depois; remova as linhas duplicadas de exemplo)
set -euo pipefail
command -v openssl >/dev/null || { echo "openssl não encontrado" >&2; exit 1; }
fernet() { openssl rand -base64 32 | tr '+/' '-_'; }
echo "SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-64)"
echo "ENCRYPTION_KEYS=$(fernet)"
echo "HEALTH_ENCRYPTION_KEYS=$(fernet)"
echo "BACKUP_ENCRYPTION_KEY=$(openssl rand -base64 32)"
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d '\n=+/' | cut -c1-32)"
echo "# IMPORTANTE: guarde BACKUP_ENCRYPTION_KEY em um cofre FORA do servidor. Sem ela, backups não podem ser restaurados." >&2
