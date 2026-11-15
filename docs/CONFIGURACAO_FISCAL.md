# Configuração fiscal — Corpo Sano Contábil (NFS-e Nacional)

> Nada é presumido pelo sistema: regime tributário, CNAE, códigos de serviço, alíquotas e obrigações
> são informados e **validados pelo contador**. Todos os tributos exibidos são **estimativas**.

## 1. Integração utilizada

Sistema Nacional NFS-e — API do Emissor Público Nacional (Sefin Nacional), conforme o
*Manual dos Contribuintes — Guia para utilização das APIs do Emissor Público Nacional* (gov.br/nfse):

| Operação | Método | Recurso |
|---|---|---|
| Emissão síncrona | `POST` | `/nfse` com `{"dpsXmlGZipB64": "..."}` (DPS assinada, GZip, Base64) |
| Consulta da NFS-e | `GET` | `/nfse/{chaveAcesso}` |
| Chave a partir da DPS | `GET` / `HEAD` | `/dps/{id}` |
| Registro de evento (cancelamento) | `POST` | `/nfse/{chaveAcesso}/eventos` com `{"pedidoRegistroEventoXmlGZipB64": "..."}` |
| Consulta de eventos | `GET` | `/nfse/{chaveAcesso}/eventos` |
| DANFSe | `GET` | ADN `/danfse/{chave}` (quando disponibilizado) |

Autenticação por **TLS mútuo** com o certificado ICP-Brasil (A1) da clínica. As URLs-base ficam em
configurações do sistema (`nfse.sefin_url_homologacao`, `nfse.sefin_url_producao`, `nfse.adn_url_*`)
com os valores públicos conhecidos — **confira-os na documentação vigente** antes de produzir.

A arquitetura é modular (`backend/app/integrations/nfse/base.py`): municípios com sistema próprio
exigem um adaptador específico do provedor, que pode ser adicionado sem alterar o restante do sistema.

## 2. Passo a passo

1. **Contábil e Fiscal › Cadastro fiscal › Empresa**: razão social, CNPJ, inscrição municipal, endereço,
   município e **código IBGE** (7 dígitos), CNAEs, regime tributário e enquadramento, situação no Simples
   (`opSimpNac`: 1 não optante · 2 MEI · 3 ME/EPP), regime de apuração do SN (`regApTribSN`, se ME/EPP),
   regime especial (`regEspTrib`), série e próximo número da DPS, versão do leiaute, dados do contador.
2. **Certificado digital**: envie o arquivo A1 (`.pfx`/`.p12`) e a senha. O sistema confere a validade e se o
   certificado pertence à raiz do CNPJ. Arquivo e senha ficam **criptografados** no servidor.
3. **Códigos de serviço**: cadastre o código de tributação nacional (`cTribNac`, 6 dígitos), o código
   municipal (se exigido), NBS, item da LC 116 e alíquota de referência, marcando quem validou.
   Vincule o código a cada serviço em **Serviços**.
4. **Instale os esquemas XSD** oficiais (ver `backend/app/integrations/nfse/xsd/README.md`).
5. **Homologação**: emita notas de teste (ambiente de produção restrita, sem validade jurídica) e confira
   o XML/DANFSe com o contador.
6. **Validação do contador**: em *Cadastro fiscal › Registrar validação*.
7. **Liberar produção** e alterar o ambiente para **Produção**. A liberação exige cadastro validado e ao
   menos uma nota autorizada em homologação. Alterar CNPJ, município, regime ou parâmetros da DPS
   **revoga** a validação e volta para homologação automaticamente.

## 3. Regras de emissão implementadas

- A nota só é **Autorizada** com resposta oficial (HTTP 201 + chave de acesso + XML da NFS-e).
- **Falha de comunicação** nunca vira autorização: a nota fica *Aguardando transmissão*; o botão
  *Reprocessar* consulta primeiro `GET /dps/{id}` e só reenvia se nenhuma NFS-e foi gerada (sem duplicidade).
- Numeração da DPS sequencial, reservada com bloqueio no banco no momento da transmissão.
- **Duplicidade bloqueada**: uma conta a receber, um pacote ou um atendimento não podem ter duas notas
  ativas; atendimentos cobertos por pacote não geram nota própria (a nota é da venda do pacote);
  nota do pacote inteiro e notas por parcela são mutuamente exclusivas.
- Assinatura XMLDSig enveloped (C14N 1.0, RSA-SHA256, `<Signature>` sem prefixo), validada nos testes
  contra a libxmlsec1.
- Cancelamento (evento e101101) e substituição (DPS com chave substituída) registrados somente após
  confirmação oficial. Todo o histórico de transmissão e eventos fica na nota.
- Prévia (XML não assinado) com checagem de pré-requisitos antes de transmitir.

## 4. Tributos, obrigações e contador

- **Tributos › Regras tributárias**: cadastre por regime, com vigência inicial/final (permite a transição
  da Reforma Tributária — IBS/CBS) e base (receita bruta, presunção ou valor fixo).
- **Apurações**: estimativa por competência sobre a receita faturada ou contratada; registre o valor
  validado, a guia (anexo), vencimento e pagamento; lance a guia em contas a pagar.
- **Obrigações**: os modelos (PGDAS-D, DAS, DASN-SIMEI, DEFIS, DCTFWeb, eSocial, EFD-Reinf, ISS, municipais)
  vêm **inativos** — ative somente os aplicáveis. O status é informado pela equipe/contador (o sistema
  não transmite declarações) e aceita recibo e comprovante.
- **Exportação para o contador**: ZIP mensal com relatórios (CSV/XLSX/PDF), XMLs, DANFSe e comprovantes,
  com histórico de envio. O perfil **Contador** acessa apenas o módulo contábil.
