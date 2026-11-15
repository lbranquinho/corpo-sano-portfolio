# Instalador Windows (instalação local)

O arquivo `CorpoSano-Setup-<versão>.exe` instala o sistema completo em um computador Windows da clínica,
sem Docker e sem precisar instalar nada antes. Ele inclui:

| Componente | Origem |
|---|---|
| Python 3.12 + bibliotecas do backend | runtime oficial (python.org) |
| Interface (React) já compilada | `frontend/dist` |
| PostgreSQL 16 (servidor e ferramentas de backup) | binários oficiais (EDB/PostgreSQL) |
| WinSW 2.12 (gerenciador de serviço) | github.com/winsw/winsw (licença MIT) |

## Requisitos

- Windows 10 ou 11 de 64 bits, 4 GB de RAM, ~1,5 GB livres.
- Conta de administrador para instalar.
- O computador precisa ficar ligado no expediente (ele é o "servidor" da clínica).

## Instalação

1. Execute `CorpoSano-Setup-1.0.0.exe`. O Windows pode exibir o aviso do SmartScreen, porque o instalador
   não tem assinatura digital de código. Clique em **Mais informações › Executar assim mesmo**.
2. Escolha os atalhos e, se outros computadores da clínica forem acessar, marque
   **Permitir acesso de outros computadores da rede** (libera a porta no Firewall, só em redes privadas).
3. Informe o **administrador** (nome, e-mail e senha provisória).
4. Informe a **porta** (padrão 8080) e, de preferência, uma **pasta para cópia extra dos backups**
   (HD externo ou pasta sincronizada do OneDrive/Google Drive).
5. Aguarde a configuração: o instalador cria o banco, gera as chaves de criptografia, aplica as migrations
   e registra os serviços. Ao final, o sistema abre em `http://localhost:8080`.

O instalador cria:

- `C:\Program Files\Corpo Sano`: programa.
- `C:\ProgramData\CorpoSano`: dados (`pgdata`, `files`, `backups`, `logs`, `corposano.env`). O acesso é restrito
  a Administradores e ao sistema.
- Serviços **CorpoSanoDB** (PostgreSQL, porta local 5544 ou a próxima livre) e **CorpoSano** (sistema).
  Os dois iniciam automaticamente e são reiniciados em caso de falha.

## Uso na rede da clínica

Nos outros computadores ou celulares da mesma rede, acesse `http://NOME-DO-COMPUTADOR:8080` ou `http://IP:8080`.
Recomenda-se fixar o IP do computador servidor no roteador (reserva DHCP).

> A instalação local usa HTTP dentro da rede interna. **Não** redirecione a porta no roteador para a internet.
> Para acesso remoto seguro, use a implantação em servidor com HTTPS ([IMPLANTACAO.md](IMPLANTACAO.md)).
> Os dados podem ser migrados depois: backup aqui, restauração no servidor (mesmas chaves).

## Backups

- Backups diários a partir das 12h, criptografados (AES-256-GCM) e verificados, em `C:\ProgramData\CorpoSano\backups`
  e na pasta de cópia extra (se informada). Também é possível fazer manualmente em **Configurações › Backups**.
- A pasta de cópia extra pode ser alterada executando o instalador novamente (deixe o campo vazio para desativar).
  Use um disco local/externo ou pasta sincronizada: o serviço roda como conta do sistema, que normalmente
  não tem acesso a pastas compartilhadas de rede.
- **Guarde uma cópia de `C:\ProgramData\CorpoSano\corposano.env` fora do computador** (pendrive guardado em local
  seguro, cofre de senhas). Ele contém as chaves: sem ele os backups não podem ser restaurados.
- Restauração (prompt de comando como administrador):

```bat
cd "C:\Program Files\Corpo Sano\app"
net stop CorpoSano
set CORPOSANO_ENV_FILE=C:\ProgramData\CorpoSano\corposano.env
..\python\python.exe -m app.cli backup-restore "C:\caminho\arquivo.dump.enc" --confirmo
net start CorpoSano
```

## Atualização e desinstalação

- **Atualizar:** execute o instalador da nova versão. Os serviços são parados, os arquivos substituídos,
  as migrations aplicadas e os dados preservados.
- **Desinstalar:** Configurações do Windows › Aplicativos › Corpo Sano. O desinstalador pergunta se deve
  apagar os dados. Por padrão, eles são mantidos em `C:\ProgramData\CorpoSano`.
- Instalação e desinstalação silenciosas (TI):

```bat
CorpoSano-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /ADMINNAME="Nome" /ADMINEMAIL=admin@clinica.com.br /ADMINPASS=SenhaProvisoria123 /PORT=8080
"C:\Program Files\Corpo Sano\unins000.exe" /VERYSILENT /REMOVEDATA=0
```

## Diagnóstico

- Logs: `C:\ProgramData\CorpoSano\logs` (`instalacao.log`, `CorpoSano.out.log`, `CorpoSano.err.log`) e
  `C:\ProgramData\CorpoSano\pgdata\log`.
- Serviços: `services.msc` › Corpo Sano / CorpoSanoDB.
- Verificação rápida: `http://localhost:8080/api/health`.

## Gerar o instalador (desenvolvedores)

Na máquina de build (Windows x64) com Python 3.12, PostgreSQL 16, Node.js e Inno Setup 6:

```bat
cd frontend && npm install && cd ..
python installer\build.py
```

O resultado fica em `entrega\CorpoSano-Setup-<versão>.exe`. Para regenerar o ícone, use `installer\make_icon.py`
(requer Pillow).

O instalador não é assinado. Para distribuição ampla, assine com um certificado de assinatura de código
(Authenticode) para evitar o aviso do SmartScreen.
