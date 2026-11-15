#!/usr/bin/env bash
# Emite o primeiro certificado HTTPS (Let's Encrypt) para o DOMAIN do .env.
# Pré-requisitos: DNS do domínio apontando para o servidor e portas 80/443 liberadas no firewall.
# Execute na pasta do ambiente ANTES do primeiro "docker compose up".
set -euo pipefail
cd "$(dirname "$0")/.."
# lê só as chaves necessárias: o .env segue o formato do Docker Compose (valores com espaço sem aspas)
# e não pode ser carregado com "source"
env_get() { grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }
DOMAIN="$(env_get DOMAIN)"
LETSENCRYPT_EMAIL="$(env_get LETSENCRYPT_EMAIL)"
: "${DOMAIN:?Defina DOMAIN no .env}"
: "${LETSENCRYPT_EMAIL:?Defina LETSENCRYPT_EMAIL no .env}"
mkdir -p certbot/conf certbot/www
docker compose stop web 2>/dev/null || true
docker run --rm -p 80:80 \
  -v "$PWD/certbot/conf:/etc/letsencrypt" -v "$PWD/certbot/www:/var/www/certbot" \
  certbot/certbot:v2.11.0 certonly --standalone -d "$DOMAIN" \
  --email "$LETSENCRYPT_EMAIL" --agree-tos --no-eff-email --non-interactive
echo "Certificado emitido. Inicie com: docker compose up -d"
