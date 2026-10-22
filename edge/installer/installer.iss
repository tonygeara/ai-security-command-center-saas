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
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if RegKeyExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OtherAppId}_is1') or
     RegKeyExists(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#OtherAppId}_is1') then
  begin
    MsgBox('{#OtherAppName} is already installed on this computer.' + #13#10 + #13#10 +
           '{#MyAppName} cannot be installed next to it, because both use the same local AI services.' + #13#10 +
           'Uninstall {#OtherAppName} first (Settings > Apps), or install on another computer.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;
  if not FileExists(ExpandConstant('{commonpf64}\Docker\Docker\Docker Desktop.exe')) then
    if MsgBox('Docker Desktop is required to run the local AI services (Frigate, MQTT, MediaMTX).' + #13#10 + #13#10 +
              'Install it from https://www.docker.com/products/docker-desktop/ before starting the app.' + #13#10 +
              'Continue installing anyway?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
end;
