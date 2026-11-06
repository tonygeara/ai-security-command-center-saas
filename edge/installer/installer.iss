; AI Security Command Center - Windows installer (Inno Setup 6).
; Built by build.ps1, which passes /DMyAppVersion from launcher.pyw.
; Installs per user (no admin). User data stays in %LOCALAPPDATA%\AI-Security-System
; and is never removed by an upgrade or uninstall.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
; build_onprem.ps1 overrides these for the "AI Command Centre Lebanon" on-prem edition.
#ifndef MyAppName
  #define MyAppName "AI Security Command Center"
#endif
#ifndef MyAppSlug
  #define MyAppSlug "AI-Security-Command-Center"
#endif
#ifndef MyAppId
  #define MyAppId "{E8BB2C1A-704F-4C0A-A971-49388F9DAE39}"
#endif
#define MyAppExeName MyAppSlug + ".exe"
; The two editions share Docker containers and ports, so never install both on one PC.
#define SaasAppId "{E8BB2C1A-704F-4C0A-A971-49388F9DAE39}"
#define OnpremAppId "{6F3C2A9E-5B1D-4E8A-9C47-2D8B1F0A7E53}"
#if MyAppId == SaasAppId
  #define OtherAppId OnpremAppId
  #define OtherAppName "AI Command Centre Lebanon"
#else
  #define OtherAppId SaasAppId
  #define OtherAppName "AI Security Command Center"
#endif

[Setup]
AppId={#StringChange(MyAppId, '{', '{{')}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=AI Security
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename={#MyAppSlug}-Setup-{#MyAppVersion}
SetupIconFile=..\assets\ai_security.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "dist\{#MyAppSlug}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Offline install: if the AI services package sits next to Setup.exe (USB stick), copy it in.
Source: "{src}\ai-command-centre-images.tar"; DestDir: "{app}\offline"; Flags: external skipifsourcedoesntexist ignoreversion
Source: "..\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; Check: not AppWasRunning
; An upgrade that had to stop the running app starts it again, also in a silent install.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: AppWasRunning

[Code]
var
  WasRunning: Boolean;

{ Is the program (the launcher or its dashboard, same .exe) running? The dashboard has no window, so Windows'
  "close the applications" step can't close it, and an upgrade failed with "DeleteFile failed; code 5". }
function AppRunning(): Boolean;
var
  Locator, Service, Procs: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''{#MyAppExeName}''');
    Result := Procs.Count > 0;
  except
    Result := False;
  end;
end;

function AppWasRunning(): Boolean;
begin
  Result := WasRunning;
end;

{ Before copying files: stop the running program (asking first, unless the install is silent). The local AI
  services in Docker keep running; the program starts again after the upgrade. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code, I: Integer;
begin
  Result := '';
  if not AppRunning() then
    exit;
  if not WizardSilent() then
    if MsgBox('{#MyAppName} is running.' + #13#10 + #13#10 +
              'Setup will stop it to update it (cameras and drones pause for about a minute) and start it again when it is done.',
              mbConfirmation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := 'Setup was cancelled because {#MyAppName} is still running. Close it and run Setup again.';
      exit;
    end;
  WasRunning := True;
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/T /F /IM "{#MyAppExeName}"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  for I := 1 to 30 do
  begin
    if not AppRunning() then
      break;
    Sleep(500);
  end;
  if AppRunning() then
    Result := 'Setup could not stop {#MyAppName}. Press Stop in its window, end it in Task Manager, then run Setup again.'
  else
    Sleep(1500); { let Windows release the program files }
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OtherAppId}_is1') or
     RegKeyExists(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OtherAppId}_is1') then
  begin
    { SuppressibleMsgBox: a silent install (/SUPPRESSMSGBOXES) takes the default answer instead of waiting for a click. }
    SuppressibleMsgBox('{#OtherAppName} is already installed on this computer.' + #13#10 + #13#10 +
           '{#MyAppName} cannot be installed next to it, because both use the same local AI services.' + #13#10 +
           'Uninstall {#OtherAppName} first (Settings > Apps), or install on another computer.', mbCriticalError, MB_OK, IDOK);
    Result := False;
    exit;
  end;
  if not FileExists(ExpandConstant('{commonpf64}\Docker\Docker\Docker Desktop.exe')) then
    if SuppressibleMsgBox('Docker Desktop is required to run the local AI services (Frigate, MQTT, MediaMTX).' + #13#10 + #13#10 +
              'Install it from https://www.docker.com/products/docker-desktop/ before starting the app.' + #13#10 +
              'Continue installing anyway?', mbConfirmation, MB_YESNO, IDYES) = IDNO then
      Result := False;
end;
