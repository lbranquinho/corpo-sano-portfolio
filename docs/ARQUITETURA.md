# Arquitetura, regras de negócio e testes

## Visão geral

```
Navegador (React SPA) ──HTTPS──> Nginx ──> FastAPI (api) ──> PostgreSQL 16
                                              │
                                   worker (mesma imagem): fila WhatsApp, lembretes, rotinas diárias, backups
                                              │
                        WhatsApp Cloud API (Graph)      Sefin Nacional / ADN (mTLS ICP-Brasil)      S3 (cópia de backup)
```

- **Backend modular**: `api/` (rotas e validação Pydantic), `services/` (regras de negócio),
  `integrations/` (adaptadores externos isolados), `models/` (SQLAlchemy), `core/` (segurança,
  criptografia, auditoria, armazenamento, configuração).
- **Fila de saída do WhatsApp** persistida no banco (outbox) — sem Redis, baixo consumo de recursos.
- **Adaptador fiscal** (`integrations/nfse/base.py`) com implementação Nacional; novos provedores municipais
  implementam a mesma interface.

## Banco de dados

56 tabelas com UUID, chaves estrangeiras, `CHECK` e índices. Destaques de integridade:

- `appointments`: restrições de exclusão GiST impedem sobreposição do mesmo profissional ou sala
  (status ativos), mesmo sob concorrência; além disso a aplicação usa *advisory locks* e considera o
  intervalo entre sessões.
- `fiscal_invoices`: índice único parcial por operação (`source_key`) para notas ativas; DPS única por
  ambiente/série/número.
- `accounts_receivable`: uma conta ativa por atendimento; valores pagos nunca maiores que o líquido.
- `package_sessions`: uma baixa ativa por atendimento; `sessions_used` entre 0 e o total.
- `cash_closings`: um fechamento por conta/dia.

Principais entidades: users, roles, permissions, user_sessions, clinics, professionals, rooms,
business_hours, holidays, schedule_blocks, customers, customer_consents, customer_health_records,
appointments, appointment_status_history, services, service_categories, package_plans, packages,
package_sessions, treatments, treatment_records, crm_leads, crm_interactions, crm_tasks, crm_campaigns,
whatsapp_messages, whatsapp_templates, financial_accounts, financial_categories, cost_centers,
financial_transactions, accounts_receivable, accounts_payable, payment_methods, expenses, cash_closings,
tax_company_settings, tax_service_codes, tax_rates, tax_assessments, fiscal_invoices, fiscal_invoice_events,
fiscal_documents, tax_obligation_templates, tax_obligations, accounting_exports, digital_certificates,
stored_files, audit_logs, system_settings, backup_history.

Migrations: `backend/alembic/versions` (estrutura inicial + restrições de conflito da agenda).

## Regras de negócio essenciais

- Agendamento **não** é receita. A conta a receber nasce na conclusão do atendimento avulso, na venda
  do pacote ou em lançamento manual. Receita recebida = entradas efetivas menos estornos.
- Sessão de pacote é baixada apenas na conclusão (ou por regra de falta/cancelamento tardio do pacote).
- Atendimento de pacote tem valor zero e não gera cobrança nem nota própria.
- Não é possível concluir atendimento futuro, registrar falta antes do horário ou lançar em dia com caixa fechado.
- NFS-e: só "autorizada" com confirmação oficial; falha de comunicação → reprocessamento seguro.
- CRM: estágio avança automaticamente com os eventos; inativação diária após N dias sem atendimento.

## Testes automatizados (`backend/tests`)

| Arquivo | Cobertura |
|---|---|
| `test_auth_permissions.py` | login, mensagens genéricas, bloqueio, troca obrigatória, rotação/revogação de sessão, perfis (recepção, contador, massoterapeuta), personalização, último admin, auditoria, cabeçalhos |
| `test_customers_agenda.py` | CPF/CNPJ, duplicidade, busca sem acento/telefone/CPF, CRM automático, conflitos (profissional, sala, intervalo), horário/feriado/bloqueio, remarcação, recorrência, restrição no banco, horários livres, anonimização |
| `test_finance_packages.py` | agendamento ≠ receita, conta a receber na conclusão, pagamento parcial/excedente, estorno, fechamento de caixa, parcelas, pacotes (baixa, falta, cancelamento tardio, saldo, outro cliente), relatórios e exportações, dashboard |
| `test_fiscal.py` | Id da DPS, assinatura e adulteração, verificação cruzada com libxmlsec1, bloqueios de emissão, duplicidade (título, pacote, atendimento), autorização simulada pela API oficial, rejeição, falha de comunicação + reprocessamento sem reenvio, produção exige validação, certificado × CNPJ, tributos sem regra, obrigações por modelo ativo, ZIP do contador |
| `test_whatsapp_security_backup.py` | fila com consentimento, bloqueio sem consentimento, integração desligada, novas tentativas, webhook (verificação, assinatura, status, recebidas, opt-out, reentrega), criptografia de dados de saúde, acesso clínico restrito, AES-GCM com detecção de adulteração, **backup e restauração real** |
