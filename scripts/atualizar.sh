#!/usr/bin/env bash
# Atualiza o ambiente: backup preventivo, nova versão do código, build e reinício (migrations automáticas).
set -euo pipefail
cd "$(dirname "$0")/.."
echo ">> Backup preventivo"
docker compose exec -T worker python -m app.cli backup
if [ -d .git ]; then echo ">> Atualizando código"; git pull --ff-only; fi
echo ">> Build"
docker compose build
echo ">> Reiniciando serviços (a API aplica as migrations)"
docker compose up -d
docker compose ps
curl -fsS "${PUBLIC_BASE_URL:-https://localhost}/api/health" || echo "Verifique o health-check manualmente."
