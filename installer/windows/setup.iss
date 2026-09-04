; Inno Setup script — builds SupermarketSystem-Setup.exe
; Prerequisite: build the app first with build.ps1 (creates dist\SupermarketSystem.exe)

#define MyAppName "Supermarket System"
#define MyAppVersion "0.1.0"
#define MyAppExeName "SupermarketSystem.exe"

[Setup]
AppId={{8B2F1D9E-4C6A-4E1A-9C6B-SUPERMARKET01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Supermarket System
DefaultDirName={autopf}\SupermarketSystem
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\output
OutputBaseFilename=SupermarketSystem-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Run {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
