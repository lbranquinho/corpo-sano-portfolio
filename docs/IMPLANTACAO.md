# Implantação em servidor (VPS ou nuvem)

Cada ambiente (**homologação** e **produção**) roda em uma pasta própria, com `.env`, banco, chaves,
domínio e certificado próprios. Recomenda-se servidores separados; se usar o mesmo, mantenha pastas
e `COMPOSE_PROJECT_NAME` distintos e coloque um proxy único na frente (ou portas diferentes).

## 1. Servidor

- Linux 64 bits (Ubuntu 24.04 LTS ou Debian 12), 2 vCPU, 2–4 GB RAM, 40 GB SSD (suficiente para uma clínica pequena).
- Docker Engine + Docker Compose v2.24+.
- Firewall: liberar somente 22 (SSH, de preferência restrito), 80 e 443.
- Usuário sem senha de root via SSH (chave), atualizações automáticas de segurança.
- DNS: registro `A` do domínio (ex.: `sistema.suaclinica.com.br`) apontando para o IP do servidor.

## 2. Primeira instalação (produção)

```bash
sudo mkdir -p /opt/corposano && sudo chown $USER /opt/corposano
cd /opt/corposano
# copie o código (git clone do seu repositório privado ou envio do pacote)
cp .env.producao.example .env
./scripts/gerar-chaves.sh      # preencha SECRET_KEY, chaves de criptografia e POSTGRES_PASSWORD no .env
nano .env                      # DOMAIN, PUBLIC_BASE_URL (https://...), LETSENCRYPT_EMAIL, INITIAL_ADMIN_*, BACKUP_S3_*
./scripts/primeiro-certificado.sh
docker compose build
docker compose up -d
docker compose ps              # api deve ficar "healthy"
```

Acesse `https://SEU_DOMINIO`, entre com o administrador inicial e troque a senha. Depois **remova**
`INITIAL_ADMIN_PASSWORD` do `.env`.

A API recusa iniciar em homologação/produção se:
- alguma chave ainda tiver valor de exemplo;
- `COOKIE_SECURE` não for `true`;
- `PUBLIC_BASE_URL` não for HTTPS.

## 3. Homologação

Igual à produção, em outra pasta (ex.: `/opt/corposano-homologacao`) com `.env.homologacao.example`,
outro domínio (ex.: `homologacao.suaclinica.com.br`) e **chaves diferentes**. Use-a para:
- validar atualizações antes de aplicar em produção;
- emitir NFS-e no ambiente de **produção restrita** do Sistema Nacional;
- treinar a equipe.

## 4. Serviços em execução

| Serviço | Função |
|---|---|
| `db` | PostgreSQL 16 (volume `db_data`, sem porta exposta) |
| `api` | FastAPI; aplica migrations no início; health-check `/api/health` |
| `worker` | fila do WhatsApp, lembretes, aniversários, pacotes expirados, clientes inativos, obrigações atrasadas, backup diário |
| `web` | Nginx: HTTPS, HSTS, CSP, limitação de requisições, arquivos do frontend, proxy para a API |
| `certbot` | renovação automática do certificado (o Nginx recarrega a cada 6 h) |

## 5. Atualizações

```bash
cd /opt/corposano
./scripts/atualizar.sh     # backup preventivo + git pull + build + up -d (migrations automáticas)
```

Sempre atualize primeiro a homologação, confira, e depois a produção.

## 6. Monitoramento

- `docker compose ps` / `docker compose logs -f api worker` (logs técnicos não incluem dados sensíveis nem tokens).
- Configure um monitor externo (ex.: UptimeRobot, Better Stack) consultando `https://SEU_DOMINIO/api/health` a cada 1–5 min.
- O Dashboard exibe alertas de backup ausente (> 26 h), certificado digital perto do vencimento,
  NFS-e aguardando confirmação, falhas de WhatsApp, obrigações atrasadas e contas vencidas.
- Os contêineres reiniciam automaticamente (`restart: unless-stopped`).

## 7. Arquivos XSD da NFS-e

Antes de emitir em produção, copie os esquemas oficiais para `backend/app/integrations/nfse/xsd/`
(ver o README da pasta) e rode `docker compose build api worker && docker compose up -d`.
