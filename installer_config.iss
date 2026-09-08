; ============================================================================
; installer_config.iss — Inno Setup 6 script for WWRecorder
;
; Prerequisites:
;   1. Build with PyInstaller first:  pyinstaller wwrecorder.spec
;   2. The dist\WWRecorder\ folder must exist and contain WWRecorder.exe
;   3. Place icon.ico in the project root (used for installer icon)
;   4. Compile with Inno Setup 6:  iscc installer_config.iss
;
; Output:
;   installer_output\WWRecorder_Setup_1.6.3.exe
; ============================================================================

#define MyAppName       "WWRecorder"
#define MyAppVersion    "1.6.3"
#define MyAppPublisher  "Sumit Kumar Lamba"
#define MyAppURL        "https://akasumitlamba.github.io/WWRecorder/"
#define MyAppExeName    "WWRecorder.exe"
#define MyAppMutex      "Global\WWRecorder_mutex"

; Path to the PyInstaller output folder
#define DistDir         "dist\WWRecorder"

; Fail at compile time instead of producing an installer without the app.
#if !FileExists(AddBackslash(SourcePath) + DistDir + "\WWRecorder.exe")
  #error "Build dist\WWRecorder first with: pyinstaller --clean --noconfirm wwrecorder.spec"
#endif

[Setup]
; ── Identity ─────────────────────────────────────────────────────────────────
AppId={{A3F2B8D1-7E4C-4F2A-9B6D-0C1E5A8F3D7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
AppMutex={#MyAppMutex}

; ── Install paths ─────────────────────────────────────────────────────────────
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes

; ── Privileges & UAC ─────────────────────────────────────────────────────────
; Per-user install avoids UAC prompt entirely
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; ── Output ────────────────────────────────────────────────────────────────────
OutputDir=installer_output
OutputBaseFilename=WWRecorder_Setup_{#MyAppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; ── Compression ───────────────────────────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ── Wizard appearance ─────────────────────────────────────────────────────────
WizardStyle=modern
WizardSizePercent=120
DisableWelcomePage=no
ShowLanguageDialog=auto

; ── Misc ──────────────────────────────────────────────────────────────────────
ArchitecturesInstallIn64BitMode=x64os
ArchitecturesAllowed=x64compatible
ChangesEnvironment=no
CloseApplications=yes
RestartApplications=no
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}


[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"


[Tasks]
; Desktop shortcut
Name: "desktopicon";     Description: "{cm:CreateDesktopIcon}";          GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Auto-start with Windows
Name: "autostart";       Description: "Launch {#MyAppName} when Windows starts"; GroupDescription: "System Integration:"


[Files]
; ── Main application (entire PyInstaller output folder) ─────────────────────
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── Additional assets (if not already in the dist folder) ───────────────────
; Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; ── Visual C++ Redistributable (optional — include if you want to ship it) ──
; Source: "redist\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall


[Icons]
; Start Menu
Name: "{group}\{#MyAppName}";          Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

; Desktop (optional task)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"


[Registry]
; ── Auto-start with Windows (mirrors in-app setting) ─────────────────────────
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#MyAppName}"; \
  ValueData: """{app}\{#MyAppExeName}"""; \
  Flags: uninsdeletevalue; Tasks: autostart

; ── App registration (for Add/Remove Programs metadata) ──────────────────────
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; \
  ValueType: string; ValueName: "InstallPath"; \
  ValueData: "{app}"; Flags: uninsdeletekey


[Run]
; ── Optional: install VC++ Redist silently ────────────────────────────────────
; Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/quiet /norestart"; \
;   StatusMsg: "Installing Visual C++ Runtime…"; \
;   Check: VCRedistNeedsInstall; Flags: waituntilterminated

; ── Launch WWRecorder after install (checkbox shown in finish page) ───────────
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent runasoriginaluser


[UninstallRun]
; Gracefully close a running instance before uninstalling
Filename: "taskkill.exe"; Parameters: "/IM {#MyAppExeName} /F"; \
  Flags: runhidden; RunOnceId: "KillApp"


[UninstallDelete]
; Remove app config from %APPDATA% only if user chose to (see Code section)
Type: dirifempty; Name: "{userappdata}\{#MyAppName}"


; ============================================================================
;  Pascal Script — helper functions
; ============================================================================
[Code]

// ── Check whether the app is currently running ─────────────────────────────
function IsAppRunning(): Boolean;
begin
  Result := CheckForMutexes('{#MyAppMutex}');
end;

// ── Pre-install: warn if already running ──────────────────────────────────
function InitializeSetup(): Boolean;
begin
  if IsAppRunning() then
  begin
    { Store-initiated installs must remain silent. Return a failure code when
      the app owns its mutex; an interactive launch may still explain why. }
    if not WizardSilent then
      MsgBox(
        '{#MyAppName} is currently running.' + #13#10 +
        'Please close it before continuing the installation.',
        mbError, MB_OK
      );
    Result := False;
  end
  else
    Result := True;
end;

// ── Pre-uninstall: gracefully close app ───────────────────────────────────
function InitializeUninstall(): Boolean;
begin
  if IsAppRunning() then
  begin
    if UninstallSilent then
      Result := False
    else if MsgBox(
      '{#MyAppName} is currently running and needs to be closed.' + #13#10 +
      'Click OK to close it and continue uninstalling, or Cancel to abort.',
      mbConfirmation, MB_OKCANCEL
    ) = IDOK then
    begin
      // taskkill is handled by UninstallRun above; we just return True
      Result := True;
    end
    else
      Result := False;
  end
  else
    Result := True;
end;

// ── Optionally delete user config on uninstall ────────────────────────────
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ConfigDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    ConfigDir := ExpandConstant('{userappdata}\{#MyAppName}');
    if DirExists(ConfigDir) and (not UninstallSilent) then
    begin
      if MsgBox(
        'Do you also want to remove your {#MyAppName} settings and recordings index?' + #13#10 +
        '(Your video files in Videos\WWRecorder will NOT be deleted.)',
        mbConfirmation, MB_YESNO
      ) = IDYES then
      begin
        DelTree(ConfigDir, True, True, True);
      end;
    end;
  end;
end;

// ── VC++ Redist check (uncomment if shipping VC++ installer) ─────────────
// function VCRedistNeedsInstall(): Boolean;
// var
//   Major: Cardinal;
// begin
//   // Check for VS2019/2022 x64 redist
//   Result := not RegQueryDWordValue(
//     HKLM,
//     'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
//     'Major', Major
//   );
// end;
