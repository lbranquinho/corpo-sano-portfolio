# Backup e restauração

## Como funciona

- **Automático**: o `worker` executa um backup diário a partir de `BACKUP_DAILY_HOUR` (padrão 3h).
- **Manual**: *Configurações › Backups › Executar backup agora* ou `./scripts/backup.sh`.
- Processo: `pg_dump` (formato custom) → criptografia **AES-256-GCM** em blocos (cada bloco autenticado,
  impede alteração e reordenação) → verificação (hash SHA-256 + descriptografia + `pg_restore --list`)
  → cópia externa (S3 compatível) → registro no histórico.
- **Retenção** local configurável (`BACKUP_RETENTION_DAYS`); configure ciclo de vida/versões no bucket externo.
- O Dashboard alerta quando não há backup bem-sucedido nas últimas 26 horas.

## Cópia fora do servidor (obrigatório para continuidade)

Preencha no `.env`: `BACKUP_S3_ENDPOINT`, `BACKUP_S3_REGION`, `BACKUP_S3_BUCKET`, `BACKUP_S3_ACCESS_KEY`,
`BACKUP_S3_SECRET_KEY`, `BACKUP_S3_PREFIX`. Funciona com AWS S3, Backblaze B2, Wasabi, MinIO etc.
Use credenciais restritas a esse bucket (somente gravação/leitura do prefixo) e habilite versionamento.

**Guarde a `BACKUP_ENCRYPTION_KEY` em um cofre de senhas fora do servidor.** Sem ela, nenhum backup
pode ser restaurado.

## Arquivos anexados

Documentos (anexos clínicos, comprovantes, XMLs, DANFSe) ficam no volume `files`, criptografados.
Inclua o volume na rotina de cópia do provedor (snapshot) ou sincronize-o periodicamente para o bucket:

```bash
docker run --rm -v corposano_files:/data:ro -v $PWD:/out alpine tar czf /out/arquivos_$(date +%F).tgz -C /data .
```

## Restauração

```bash
cd /opt/corposano
./scripts/restaurar.sh /caminho/corposano_production_AAAAMMDD_HHMMSS.dump.enc
```

O script oferece um backup de segurança do estado atual, pede confirmação digitando `RESTAURAR`,
para a API, restaura em transação única e reinicia os serviços. Restaurações **não** são feitas pela
interface web, para evitar sobrescrita acidental.

Para validar periodicamente (recomendado mensalmente), restaure o backup mais recente no ambiente de
**homologação** e confira os dados. A suíte de testes inclui um teste real de backup + restauração.

## Plano de recuperação de desastres

| Cenário | Ação | Objetivo |
|---|---|---|
| Erro humano (dados apagados) | Restaurar o backup do dia anterior em homologação, extrair o necessário | RPO ≤ 24 h |
| Falha do servidor | Novo servidor → instalar (docs/IMPLANTACAO.md) → copiar `.env` do cofre → baixar último backup do bucket → `restaurar.sh` → restaurar volume `files` | RTO ≈ 2–4 h |
| Comprometimento | Revogar tokens (Meta), trocar senhas, gerar novas chaves `SECRET_KEY`/`ENCRYPTION_KEYS` (mantendo as antigas como chaves secundárias para leitura), restaurar backup íntegro | — |

Rotação de chaves: `ENCRYPTION_KEYS` e `HEALTH_ENCRYPTION_KEYS` aceitam várias chaves separadas por vírgula —
a primeira cifra novos dados; as demais continuam decifrando os antigos.
