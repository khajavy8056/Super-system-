; Inno Setup script - builds SupermarketSystem-Setup-<version>.exe
; Prerequisite: build the app first with build.ps1 (creates dist\SupermarketSystem.exe)
;
; STATUS (honest): this script is maintained and syntax-reviewed, but building
; the Windows Setup.exe was NOT possible in the development sandbox (no
; Windows / no Inno Setup). Verified paths instead:
;   - the frozen-app launcher logic (run_supermarket.py) was built with
;     cx_Freeze on Linux and boot-tested end-to-end (health/login/frontend/DB).
;   - see docs/BUILD.md for the full Windows build procedure to run locally.
;   - or just double-click BUILD-SETUP.bat in this folder.

#define MyAppName "Supermarket System"
; The build scripts pass the real version with /DMyAppVersion=<x.y.z>, read from
; backend\app\__init__.py so the installer filename can never drift from what the
; application reports. Redefining an existing symbol is an error in Inno Setup,
; hence the guard: this default only applies when ISCC is invoked by hand.
#ifndef MyAppVersion
  #define MyAppVersion "1.2.3"
#endif
#define MyAppExeName "SupermarketSystem.exe"
#define MyAppPublisher "Supermarket System"
#define MyAppURL "https://example.invalid/"

[Setup]
; A real GUID. The previous value contained "SUPERMARKET01", which is not
; valid hexadecimal, so Windows could mis-register the product and break
; upgrade/uninstall detection. Fixed and stable: changing it later would make
; Windows treat an upgrade as a separate product.
AppId={{B1969066-0725-5BAD-AC99-E4201ADBDE6B}
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
; Upgrading in place must never destroy the shop's database (§29). Data lives
; in %USERPROFILE%\SupermarketSystem and is never written to {app}.
UsePreviousAppDir=yes
UsePreviousGroup=yes
OutputDir=..\output
OutputBaseFilename=SupermarketSystem-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; --- Correct size on every monitor -----------------------------------------
; The wizard is laid out in dialog units and rescaled from the system DPI.
; Without these two lines the window is bitmap-stretched (blurry) on a 4K or
; 150%-scaled display, which is the single most common "looks broken" report.
WizardSizePercent=120
WizardResizable=yes
; "x64", NOT "x64compatible": the latter is unknown to Inno Setup 6.0-6.2 and
; aborts compilation ("Unrecognised identifier"). x64 works on every 6.x.
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes
; Refuse to run on anything older than Windows 7 SP1 with a clear message
; rather than failing with an obscure Windows error mid-install.
MinVersion=6.1sp1

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; Farsi translation: download Farsi.isl from jrsoftware.org's unofficial translations
; (https://jrsoftware.org/files/istrans/) into compiler:Languages\, then uncomment:
; Name: "farsi"; MessagesFile: "compiler:Languages\Farsi.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
; Fail early and legibly if the app was never built.
#if !FileExists("dist\" + MyAppExeName)
  #error dist\SupermarketSystem.exe not found. Run BUILD-SETUP.bat (or build.ps1) first.
#endif
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; delete app files only - user DATA in %USERPROFILE%\SupermarketSystem (DB, logs,
; secret key) is intentionally NOT touched by uninstall
Type: filesandordirs; Name: "{app}"

[Messages]
; Notes shown on the final page (English; Farsi.isl ships its own when present)
FinishedLabelNoIcons=Setup has installed [name]. Your data is stored in your user profile folder (SupermarketSystem) and is kept when you update or uninstall.
FinishedLabel=Setup has installed [name]. Your data is stored in your user profile folder (SupermarketSystem) and is kept when you update or uninstall.
