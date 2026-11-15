# Esquemas XSD oficiais da NFS-e Nacional

Coloque nesta pasta os esquemas oficiais publicados em
<https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual>
(pacote **"NFSe-ESQUEMAS_XSD"** da versão vigente).

O Corpo Sano procura, para a versão de leiaute configurada no cadastro fiscal (ex.: `1.01`):

| Documento | Nome esperado do arquivo principal |
|-----------|------------------------------------|
| DPS | `DPS_v1.01.xsd` |
| Pedido de registro de evento | `pedRegEvento_v1.00.xsd` (versão do leiaute de eventos) |

Copie **todos** os arquivos do pacote (os esquemas principais importam os de tipos/assinatura).
Se os nomes do pacote vigente forem diferentes, renomeie/crie uma cópia com o nome esperado.

- Com os esquemas instalados, a DPS é validada **antes** da assinatura e do envio.
- Em **produção**, a presença do esquema da DPS é pré-requisito obrigatório para transmitir.
- Em homologação, sem os esquemas, a validação fica a cargo do serviço oficial (o retorno é exibido na nota).

No Docker, monte esta pasta como volume ou copie os arquivos antes do `docker compose build`.
