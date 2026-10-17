; AI Security Command Center - Windows installer (Inno Setup 6).
; Built by build.ps1, which passes /DMyAppVersion from launcher.pyw.
; Installs per user (no admin). User data stays in %LOCALAPPDATA%\AI-Security-System
; and is never removed by an upgrade or uninstall.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "AI Security Command Center"
#define MyAppExeName "AI-Security-Command-Center.exe"

[Setup]
AppId={{E8BB2C1A-704F-4C0A-A971-49388F9DAE39}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=AI Security
DefaultDirName={localappdata}\Programs\AI Security Command Center
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=AI-Security-Command-Center-Setup-{#MyAppVersion}
SetupIconFile=..\assets\ai_security.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "dist\AI-Security-Command-Center\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
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
  if not FileExists(ExpandConstant('{commonpf64}\Docker\Docker\Docker Desktop.exe')) then
    if MsgBox('Docker Desktop is required to run the local AI services (Frigate, MQTT, MediaMTX).' + #13#10 + #13#10 +
              'Install it from https://www.docker.com/products/docker-desktop/ before starting the app.' + #13#10 +
              'Continue installing anyway?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
end;
