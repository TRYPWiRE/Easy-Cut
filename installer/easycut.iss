; Easy-Cut installer (Inno Setup 6.3+).  Built by build.bat - don't run by hand unless you pass /DMyAppVersion=x.y.z
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppName "Easy-Cut"
#define MyAppExe "Easy-Cut.exe"
#define MyAppPublisher "TRYPWiRE"
#define MyAppURL "https://github.com/TRYPWiRE/Easy-Cut"

[Setup]
AppId={{6E1B7C2A-4F1D-4E8B-9C35-EA5C0D7B1E21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; per-user install: no admin prompt, and silent auto-updates never need elevation
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=EasyCutSetup-{#MyAppVersion}
SetupIconFile=..\assets\easycut.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "assoc"; Description: "Open Easy-Cut projects (.ecut) with Easy-Cut"; GroupDescription: "File types:"
Name: "openwith"; Description: "Add Easy-Cut to ""Open with"" for video files"; GroupDescription: "File types:"; Flags: unchecked

[Files]
Source: "..\dist\Easy-Cut\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; .ecut project files
Root: HKA; Subkey: "Software\Classes\.ecut"; ValueType: string; ValueName: ""; ValueData: "EasyCut.Project"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\EasyCut.Project"; ValueType: string; ValueName: ""; ValueData: "Easy-Cut Project"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\EasyCut.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\EasyCut.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Tasks: assoc
; "Open with" for common video files
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.mp4\OpenWithList\{#MyAppExe}"; ValueType: none; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.mov\OpenWithList\{#MyAppExe}"; ValueType: none; Flags: uninsdeletekey; Tasks: openwith
Root: HKA; Subkey: "Software\Classes\.mkv\OpenWithList\{#MyAppExe}"; ValueType: none; Flags: uninsdeletekey; Tasks: openwith

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
; silent auto-update: reopen the app afterwards
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: ShouldRelaunch

[UninstallDelete]
; caches only - settings, themes and extensions in %APPDATA%\Easy-Cut are kept
Type: filesandordirs; Name: "{userappdata}\Easy-Cut\cache"
Type: filesandordirs; Name: "{userappdata}\Easy-Cut\render"
Type: filesandordirs; Name: "{userappdata}\Easy-Cut\preview"
Type: filesandordirs; Name: "{userappdata}\Easy-Cut\stabilize"

[Code]
function ShouldRelaunch(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

function InitializeSetup(): Boolean;
begin
  // give a closing Easy-Cut a moment to exit before files are replaced
  if WizardSilent() then
    Sleep(1500);
  Result := True;
end;
