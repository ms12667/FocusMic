; FocusMic AI runtime (PyTorch 2.9.1 + CUDA 12.8), per-user installer.
; Kept separate from the main app so every GitHub release asset stays below
; the 2 GiB limit.  Build with:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\FocusMic-Runtime.iss

#define MyRuntimeName "FocusMic AI Runtime"
#define MyRuntimeVersion "2.9.1-cu128"
#define MyAppPublisher "FocusMic"
#define MyAppURL "https://github.com/ms12667/FocusMic"

[Setup]
AppId={{23f6390e-6ba8-461a-9a90-54cdc115a7fb}
AppName={#MyRuntimeName}
AppVersion={#MyRuntimeVersion}
AppVerName={#MyRuntimeName} {#MyRuntimeVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\FocusMic\runtime
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=FocusMic-Runtime-{#MyRuntimeVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#MyRuntimeName}
AppMutex=FocusMicAppMutex
VersionInfoVersion=2.9.1.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyRuntimeName} Setup
VersionInfoProductName={#MyRuntimeName}
SetupIconFile=..\focusmic\assets\icons\focusmic_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\build-tools\runtime\payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD_PARTY_LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
