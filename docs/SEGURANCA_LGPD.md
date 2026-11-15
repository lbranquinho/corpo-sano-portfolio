# Segurança e LGPD

## Controles implementados

| Requisito | Implementação |
|---|---|
| HTTPS | Nginx com TLS 1.2/1.3 (Let's Encrypt), redirecionamento 80→443, HSTS |
| Autenticação individual | e-mail + senha por usuário; senha provisória com troca obrigatória |
| Hash de senhas | Argon2id (parâmetros RFC 9106), rehash automático |
| Sessões | JWT de 15 min em memória + refresh token rotativo em cookie `HttpOnly; Secure; SameSite=Strict`; sessões listáveis e revogáveis; bloqueio por inatividade (configurável) |
| Força bruta | bloqueio após 5 tentativas (15 min), mensagens genéricas, tempo de resposta equivalente, limite por IP/e-mail |
| Rate limiting | API (por IP) + Nginx (`limit_req` geral e no login) |
| Proteção de APIs | permissões verificadas em todas as rotas; massoterapeuta restrito à própria agenda/clientes; contador restrito ao módulo contábil |
| Ataques comuns | ORM com consultas parametrizadas (SQL injection), React com escape (XSS), CSP sem scripts inline, `X-Frame-Options DENY`, cookies SameSite, validação Pydantic, upload com tipo/assinatura/tamanho verificados, XML sem entidades externas |
| Auditoria | login/logout, falhas, alterações de usuários/permissões, dados de clientes, leituras de dados clínicos, pagamentos, estornos, emissões/cancelamentos fiscais, configurações, backups, exportações |
| Criptografia | credenciais (tokens WhatsApp, certificado e senha) e arquivos com Fernet; **dados de saúde com chave exclusiva**; backups AES-256-GCM |
| Segredos | somente em variáveis de ambiente/.env fora do versionamento; tokens nunca retornam ao frontend; logs sem dados sensíveis |
| Separação de permissões | áreas administrativa, clínica, financeira e fiscal com permissões independentes |

## LGPD

- **Base legal e consentimento**: registro imutável por tipo (dados pessoais, dados de saúde, WhatsApp de
  agendamento, WhatsApp de relacionamento, e-mail), com data, origem, responsável e IP.
- **Dados sensíveis (art. 11)**: anamnese e fichas com aceite eletrônico, criptografia dedicada, acesso
  restrito e auditado; nunca enviados por WhatsApp nem incluídos nas exportações ao contador.
- **Direitos do titular**: acesso/portabilidade (exportação JSON completa), correção (edição do cadastro),
  revogação de consentimento, **anonimização** quando cabível — preservando registros fiscais e financeiros
  exigidos por lei.
- **Retenção**: parâmetro de revisão de clientes inativos (anos). Recomenda-se definir a política com
  assessoria jurídica/contábil (ex.: documentos fiscais por no mínimo 5 anos).
- **Minimização**: CPF opcional; mensagens sem dados clínicos; perfis com o mínimo necessário.

## Recomendações operacionais

- Ative 2FA nos e-mails e na conta Meta/Business; restrinja SSH por chave.
- Revise mensalmente usuários ativos e a trilha de auditoria (Usuários › Auditoria).
- Teste a restauração de backup mensalmente em homologação.
- Mantenha o servidor atualizado (`unattended-upgrades`) e rode `./scripts/atualizar.sh` após validar em homologação.
- Defina um encarregado (DPO) e o aviso de privacidade da clínica.
