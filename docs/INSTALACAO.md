# Instalação — ambiente de desenvolvimento

Há duas formas: **Docker** (mais simples) ou **execução nativa** (para programar no código).

## 1. Docker (recomendado)

Pré-requisitos: Docker Engine 24+ com Docker Compose v2.24+.

```bash
cp .env.example .env
./scripts/gerar-chaves.sh          # cole os valores no .env no lugar dos "trocar-..."
# defina também INITIAL_ADMIN_EMAIL e INITIAL_ADMIN_PASSWORD (mín. 10 caracteres, letras e números)
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

- Sistema: <http://localhost:8080>
- Documentação interativa da API (somente fora de produção): <http://localhost:8080/api/docs>
- Banco exposto apenas em `127.0.0.1:5433` (para ferramentas de consulta).

A API aplica as migrations automaticamente ao iniciar e cria os dados de referência
(perfis, permissões, formas de pagamento, categorias financeiras, modelos de obrigações **inativos**).
Nenhum cliente, serviço, preço ou alíquota fictícios são criados.

## 2. Execução nativa

Pré-requisitos: Python 3.12, Node.js 20+ (LTS), PostgreSQL 16.

### Banco

```sql
CREATE ROLE corposano LOGIN PASSWORD '...' CREATEDB;
CREATE DATABASE corposano OWNER corposano;
CREATE DATABASE corposano_test OWNER corposano;   -- para os testes
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m app.cli generate-keys                     # copie para backend/.env
```

`backend/.env` mínimo:

```
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg://corposano:SENHA@localhost:5432/corposano
TEST_DATABASE_URL=postgresql+psycopg://corposano:SENHA@localhost:5432/corposano_test
SECRET_KEY=...
ENCRYPTION_KEYS=...
HEALTH_ENCRYPTION_KEYS=...
BACKUP_ENCRYPTION_KEY=...
COOKIE_SECURE=false
PUBLIC_BASE_URL=http://localhost:5173
INITIAL_ADMIN_EMAIL=admin@suaclinica.com.br
INITIAL_ADMIN_PASSWORD=SenhaProvisoria123
```

```bash
alembic upgrade head
uvicorn app.main:app --reload --port 8000
python -m app.worker        # em outro terminal (fila do WhatsApp, lembretes, backups)
```

> **Windows:** se a pasta do projeto tiver caminho muito longo, crie o ambiente virtual em um caminho curto
> (ex.: `%USERPROFILE%\.venvs\corposano`) — algumas bibliotecas compiladas falham com caminhos > 260 caracteres.
> Para backups locais, aponte `PG_DUMP_PATH`/`PG_RESTORE_PATH` para o `bin` do PostgreSQL instalado.

### Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (encaminha /api para a porta 8000)
npm run build        # build de produção (verificação de tipos incluída)
```

### Testes

```bash
cd backend && pytest -q
```

Os testes recriam o esquema do banco de testes a cada execução (nunca aponte `TEST_DATABASE_URL`
para um banco com dados reais). Opcional: `pip install xmlsec` habilita a validação cruzada da
assinatura XML com a libxmlsec1.
