#!/usr/bin/env bash
# Backup manual imediato (criptografado, verificado e enviado para a cópia externa, se configurada).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T worker python -m app.cli backup
docker compose exec -T worker sh -c 'ls -lh /backups | tail -n 5'
