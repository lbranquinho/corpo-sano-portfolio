#!/usr/bin/env bash
# Restaura um backup criptografado (.dump.enc) sobre o banco DESTE ambiente.
# Uso: ./scripts/restaurar.sh /caminho/corposano_production_AAAAMMDD_HHMMSS.dump.enc
# ATENÇÃO: substitui todos os dados atuais. Faça um backup antes (o script oferece).
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?Informe o arquivo de backup}"
[ -f "$FILE" ] || { echo "Arquivo não encontrado: $FILE" >&2; exit 1; }
read -r -p "Gerar um backup de segurança do estado atual antes? [S/n] " ans
if [ "${ans:-S}" != "n" ]; then docker compose exec -T worker python -m app.cli backup || true; fi
read -r -p "Digite RESTAURAR para substituir o banco atual: " confirm
[ "$confirm" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }
NAME="$(basename "$FILE")"
docker compose stop api
docker compose cp "$FILE" "worker:/backups/$NAME"
docker compose exec -T worker python -m app.cli backup-restore "/backups/$NAME" --confirmo
docker compose start api
docker compose restart worker
echo "Restauração concluída. Confira o acesso e os dados no sistema."
