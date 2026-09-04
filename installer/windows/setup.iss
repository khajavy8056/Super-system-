; Inno Setup script — builds SupermarketSystem-Setup-<version>.exe
; Prerequisite: build the app first with build.ps1 (creates dist\SupermarketSystem.exe)
;
; STATUS (honest): this script is maintained and syntax-reviewed, but building
; the Windows Setup.exe was NOT possible in the development sandbox (no
; Windows / no Inno Setup). Verified paths instead:
;   - the frozen-app launcher logic (run_supermarket.py) was built with
;     cx_Freeze on Linux and boot-tested end-to-end (health/login/frontend/DB).
;   - see docs/BUILD.md for the full Windows build procedure to run locally.

#define MyAppName "Supermarket System"
#define MyAppVersion "0.1.0"
#define MyAppExeName "SupermarketSystem.exe"
#define MyAppPublisher "Supermarket System"
#define MyAppURL "https://example.invalid/"

[Setup]
AppId={{8B2F1D9E-4C6A-4E1A-9C6B-SUPERMARKET01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\SupermarketSystem
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install (no admin needed): data lives in the user profile anyway.
PrivilegesRequired=lowest
OutputDir=..\output
OutputBaseFilename=SupermarketSystem-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Farsi translation: download Farsi.isl from jrsoftware.org's unofficial translations
; (https://jrsoftware.org/files/istrans/) into compiler:Languages\, then uncomment:
; Name: "farsi"; MessagesFile: "compiler:Languages\Farsi.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; stop the app if running (best effort) before deleting files
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#MyAppExeName} /F"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
; delete app files only — user DATA in %USERPROFILE%\SupermarketSystem (DB, logs,
; secret key) is intentionally NOT touched by uninstall
Type: filesandordirs; Name: "{app}"

[Messages]
; Notes shown on the final page (English; Farsi.isl ships its own when present)
FinishedLabelNoIcons=Setup has installed [name]. Your data is stored in your user profile folder (SupermarketSystem) and is kept when you update or uninstall.
FinishedLabel=Setup has installed [name]. Your data is stored in your user profile folder (SupermarketSystem) and is kept when you update or uninstall.
