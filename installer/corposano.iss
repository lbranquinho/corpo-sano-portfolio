; Corpo Sano — instalador Windows (Inno Setup 6)
; Compilado por installer\build.py:  ISCC /DStageDir=... /DOutputDir=... /DAppVersion=1.0.0 corposano.iss
;
; Parâmetros para instalação silenciosa (opcional):
;   /VERYSILENT /SUPPRESSMSGBOXES /ADMINNAME="Nome" /ADMINEMAIL=email /ADMINPASS=senha /PORT=8080 /MIRROR="D:\Backups"
; Desinstalação silenciosa apagando os dados:  unins000.exe /VERYSILENT /REMOVEDATA=1

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef StageDir
  #error "Defina StageDir (use installer\build.py)"
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{7C3A1F52-9B4E-4C6D-8E21-5A0D3F6B9C17}
AppName=Corpo Sano
AppVersion={#AppVersion}
AppVerName=Corpo Sano {#AppVersion}
AppPublisher=Corpo Sano
AppComments=Gestão para clínica de massoterapia — instalação local
DefaultDirName={autopf}\Corpo Sano
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=CorpoSano-Setup-{#AppVersion}
SetupIconFile={#StageDir}\corposano.ico
UninstallDisplayIcon={app}\corposano.ico
UninstallDisplayName=Corpo Sano
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=no
InfoAfterFile={#StageDir}\LEIA-ME.txt

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"
Name: "firewall"; Description: "Permitir acesso de outros computadores da rede da clínica (libera a porta no Firewall do Windows para redes privadas)"; GroupDescription: "Rede:"; Flags: unchecked

[Files]
Source: "{#StageDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\web\*"; DestDir: "{app}\web"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\pgsql\*"; DestDir: "{app}\pgsql"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\service\*"; DestDir: "{app}\service"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\setup\*"; DestDir: "{app}\setup"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\corposano.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[INI]
Filename: "{app}\Corpo Sano.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://localhost:{code:GetPort}"
Filename: "{app}\Corpo Sano.url"; Section: "InternetShortcut"; Key: "IconFile"; String: "{app}\corposano.ico"
Filename: "{app}\Corpo Sano.url"; Section: "InternetShortcut"; Key: "IconIndex"; String: "0"

[Icons]
Name: "{autoprograms}\Corpo Sano"; Filename: "{app}\Corpo Sano.url"; IconFilename: "{app}\corposano.ico"
Name: "{autoprograms}\Corpo Sano - Leia-me"; Filename: "{app}\LEIA-ME.txt"
Name: "{autodesktop}\Corpo Sano"; Filename: "{app}\Corpo Sano.url"; IconFilename: "{app}\corposano.ico"; Tasks: desktopicon

[Run]
Filename: "http://localhost:{code:GetPort}"; Description: "Abrir o Corpo Sano agora"; Flags: postinstall shellexec nowait skipifsilent; Check: SetupOk

[UninstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\service"
Type: filesandordirs; Name: "{app}\pgsql"
Type: filesandordirs; Name: "{app}\setup"
Type: files; Name: "{app}\Corpo Sano.url"
Type: dirifempty; Name: "{app}"

[Code]
var
  AdminPage, NetPage: TInputQueryWizardPage;
  SetupSucceeded: Boolean;
  RemoveDataAnswer: String;

function DataDir(): String;
begin
  Result := ExpandConstant('{commonappdata}\CorpoSano');
end;

function IsUpgrade(): Boolean;
begin
  { instalação anterior concluída (banco com administrador): o administrador inicial não é pedido novamente }
  Result := FileExists(DataDir() + '\instalacao.ok');
end;

function ReadEnvValue(Key: String): String;
var
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  if LoadStringsFromFile(DataDir() + '\corposano.env', Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Pos(Key + '=', Lines[I]) = 1 then
        Result := Copy(Lines[I], Length(Key) + 2, MaxInt);
end;

function GetPort(Param: String): String;
begin
  Result := Trim(NetPage.Values[0]);
  if Result = '' then
    Result := '8080';
end;

function SetupOk(): Boolean;
begin
  Result := SetupSucceeded;
end;

function HasLetterAndDigit(S: String): Boolean;
var
  I: Integer;
  HasL, HasD: Boolean;
  C: Char;
begin
  HasL := False;
  HasD := False;
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if (C >= '0') and (C <= '9') then
      HasD := True
    else if ((C >= 'a') and (C <= 'z')) or ((C >= 'A') and (C <= 'Z')) then
      HasL := True;
  end;
  Result := HasL and HasD;
end;

procedure InitializeWizard;
begin
  AdminPage := CreateInputQueryPage(wpSelectTasks,
    'Administrador do sistema', 'Crie o primeiro usuário administrador',
    'Este usuário terá acesso completo. A senha é provisória: o sistema pedirá uma nova no primeiro acesso.');
  AdminPage.Add('Nome:', False);
  AdminPage.Add('E-mail (será o login):', False);
  AdminPage.Add('Senha provisória (mínimo 10 caracteres, com letras e números):', True);
  AdminPage.Add('Confirme a senha:', True);
  AdminPage.Values[0] := ExpandConstant('{param:ADMINNAME|Administrador}');
  AdminPage.Values[1] := ExpandConstant('{param:ADMINEMAIL|}');
  AdminPage.Values[2] := ExpandConstant('{param:ADMINPASS|}');
  AdminPage.Values[3] := ExpandConstant('{param:ADMINPASS|}');

  NetPage := CreateInputQueryPage(AdminPage.ID,
    'Acesso e backups', 'Porta de acesso e cópia de segurança dos backups',
    'O sistema será aberto no navegador em http://localhost:PORTA. Recomendamos informar uma pasta para cópia extra ' +
    'dos backups diários (HD externo ou pasta sincronizada do OneDrive/Google Drive).');
  NetPage.Add('Porta (padrão 8080):', False);
  NetPage.Add('Pasta para cópia extra dos backups (opcional):', False);
  NetPage.Values[0] := ExpandConstant('{param:PORT|8080}');
  NetPage.Values[1] := ExpandConstant('{param:MIRROR|}');
  { atualização: valores atuais pré-preenchidos, salvo quando informados na linha de comando (/PORT, /MIRROR) }
  if IsUpgrade() then
  begin
    if (ExpandConstant('{param:PORT|}') = '') and (ReadEnvValue('LOCAL_PORT') <> '') then
      NetPage.Values[0] := ReadEnvValue('LOCAL_PORT');
    if (ExpandConstant('{param:MIRROR|}') = '') and (ReadEnvValue('BACKUP_MIRROR_DIR') <> '') then
      NetPage.Values[1] := ReadEnvValue('BACKUP_MIRROR_DIR');
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = AdminPage.ID) and IsUpgrade();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  P: Integer;
begin
  { SuppressibleMsgBox: na instalação silenciosa (/SUPPRESSMSGBOXES) não abre janela; um parâmetro inválido
    faz NextButtonClick devolver False e o instalador encerrar com erro, sem ficar aguardando. }
  Result := True;
  if CurPageID = AdminPage.ID then
  begin
    if Length(Trim(AdminPage.Values[0])) < 2 then
    begin
      SuppressibleMsgBox('Informe o nome do administrador.', mbError, MB_OK, IDOK);
      Result := False;
    end
    else if (Pos('@', AdminPage.Values[1]) < 2) or (Pos('.', AdminPage.Values[1]) = 0) then
    begin
      SuppressibleMsgBox('Informe um e-mail válido (ele será o login).', mbError, MB_OK, IDOK);
      Result := False;
    end
    else if (Length(AdminPage.Values[2]) < 10) or (not HasLetterAndDigit(AdminPage.Values[2])) then
    begin
      SuppressibleMsgBox('A senha deve ter no mínimo 10 caracteres, com letras e números.', mbError, MB_OK, IDOK);
      Result := False;
    end
    else if AdminPage.Values[2] <> AdminPage.Values[3] then
    begin
      SuppressibleMsgBox('A confirmação não confere com a senha.', mbError, MB_OK, IDOK);
      Result := False;
    end;
  end
  else if CurPageID = NetPage.ID then
  begin
    P := StrToIntDef(Trim(NetPage.Values[0]), 0);
    if (P < 1024) or (P > 65535) then
    begin
      SuppressibleMsgBox('Porta inválida. Use um número entre 1024 e 65535 (padrão 8080).', mbError, MB_OK, IDOK);
      Result := False;
    end
    else if (Trim(NetPage.Values[1]) <> '') and (not DirExists(Trim(NetPage.Values[1]))) then
      Result := SuppressibleMsgBox('A pasta de cópia dos backups não existe e será criada. Continuar?',
                                   mbConfirmation, MB_YESNO, IDYES) = IDYES;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  RC: Integer;
begin
  { Atualização: para os serviços para que os arquivos possam ser substituídos }
  Exec(ExpandConstant('{sys}\net.exe'), 'stop CorpoSano', '', SW_HIDE, ewWaitUntilTerminated, RC);
  Exec(ExpandConstant('{sys}\net.exe'), 'stop CorpoSanoDB', '', SW_HIDE, ewWaitUntilTerminated, RC);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Params: TArrayOfString;
  ParamFile, Args: String;
  RC: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    ParamFile := ExpandConstant('{tmp}\cs-params.txt');
    SetArrayLength(Params, 6);
    Params[0] := 'admin_name=' + Trim(AdminPage.Values[0]);
    Params[1] := 'admin_email=' + Trim(AdminPage.Values[1]);
    Params[2] := 'admin_password=' + AdminPage.Values[2];
    Params[3] := 'port=' + GetPort('');
    Params[4] := 'mirror_dir=' + Trim(NetPage.Values[1]);
    if WizardIsTaskSelected('firewall') then
      Params[5] := 'firewall=1'
    else
      Params[5] := 'firewall=0';
    SaveStringsToUTF8File(ParamFile, Params, False);
    WizardForm.StatusLabel.Caption := 'Configurando o banco de dados e os serviços do Windows (pode levar alguns minutos)...';
    Args := '-I "' + ExpandConstant('{app}\setup\instalar.py') + '" --app-dir "' + ExpandConstant('{app}') +
            '" --data-dir "' + DataDir() + '" --params "' + ParamFile + '"';
    if Exec(ExpandConstant('{app}\python\python.exe'), Args, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, RC) and (RC = 0) then
      SetupSucceeded := True
    else
    begin
      SetupSucceeded := False;
      SuppressibleMsgBox('Não foi possível concluir a configuração do Corpo Sano (código ' + IntToStr(RC) + ').' + #13#10 +
        'Consulte o registro em ' + DataDir() + '\logs\instalacao.log e execute o instalador novamente.',
        mbError, MB_OK, IDOK);
    end;
    DeleteFile(ParamFile);
  end;
end;

{ Desinstalação: remove os serviços (e, se confirmado, os dados) antes de apagar os arquivos do programa }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  RC: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if UninstallSilent() then
      RemoveDataAnswer := ExpandConstant('{param:REMOVEDATA|0}')
    else if MsgBox('Deseja apagar também os DADOS do Corpo Sano (banco de dados, anexos, backups e configuração em ' +
                   DataDir() + ')?' + #13#10#13#10 +
                   'Escolha NÃO se pretende reinstalar ou guardar os dados. Apagar não pode ser desfeito.',
                   mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      RemoveDataAnswer := '1'
    else
      RemoveDataAnswer := '0';
    if RemoveDataAnswer <> '1' then
      RemoveDataAnswer := '0';
    Exec(ExpandConstant('{app}\python\python.exe'),
         '-I "' + ExpandConstant('{app}\setup\desinstalar.py') + '" --app-dir "' + ExpandConstant('{app}') +
         '" --data-dir "' + DataDir() + '" --remove-data ' + RemoveDataAnswer,
         '', SW_HIDE, ewWaitUntilTerminated, RC);
  end;
end;
