; ============================================================================
; installer_config.iss — Inno Setup 6 script for WWRecorder
;
; Prerequisites:
;   1. Build with PyInstaller first:  ./scripts/build-distributions.ps1 -Format Both
;   2. The work\payloads\dual\WWRecorder\ folder must exist and contain WWRecorder.exe
;   3. Keep app\icon.ico with shared source (used for installer icon)
;   4. Compile with Inno Setup 6:  iscc packaging\exe\installer_config.iss
;
; Output:
;   artifacts\windows\1.7.0\local-test\exe\WWRecorder_Setup_1.7.0_local-test.exe
; ============================================================================

#define MyAppName       "WWRecorder"
#define MyAppVersion    "1.7.1"
#define MyAppPublisher  "Sumit Kumar Lamba"
#define MyAppURL        "https://akasumitlamba.github.io/WWRecorder/"
#define MyAppExeName    "WWRecorder.exe"
#define MyAppMutex      "Local\WWRecorder_mutex"

; Path to the PyInstaller output folder
#define RepoRoot AddBackslash(SourcePath) + "..\..\"
#ifndef DistDir
  #define DistDir       RepoRoot + "work\payloads\dual\WWRecorder"
#endif

; Fail at compile time instead of producing an installer without the app.
#if !FileExists(AddBackslash(DistDir) + "WWRecorder.exe")
  #error "Build shared payload first with scripts/build-distributions.ps1"
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
OutputDir={#RepoRoot}artifacts\windows\{#MyAppVersion}\local-test\exe
OutputBaseFilename=WWRecorder_Setup_{#MyAppVersion}_local-test
SetupIconFile={#RepoRoot}app\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; ── Compression ───────────────────────────────────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ── Wizard appearance ─────────────────────────────────────────────────────────
WizardStyle=modern dark windows11
WizardSizePercent=110
WizardSmallImageFile={#RepoRoot}packaging\shared\icon-source.png
WizardImageFile={#RepoRoot}packaging\exe\assets\welcome.png
WizardImageStretch=yes
WizardImageBackColor=$1D1511
WizardImageBackColorDynamicDark=$1D1511
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


[Messages]
WizardSelectTasks=Additional options
SelectTasksDesc=Choose how WWRecorder starts and where shortcuts appear.
SelectTasksLabel2=Select the options you want, then click Next.
WelcomeLabel1=Welcome to WWRecorder Setup
WelcomeLabel2=Install WWRecorder to capture your screen, microphone and computer audio.
FinishedHeadingLabel=WWRecorder is ready
FinishedLabelNoIcons=Setup has installed WWRecorder on your computer. Click Finish to close Setup.

[Tasks]
; Desktop shortcut
Name: "desktopicon";     Description: "{cm:CreateDesktopIcon}";          GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Auto-start with Windows
Name: "autostart";       Description: "Launch {#MyAppName} when Windows starts"; GroupDescription: "Startup:"


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


[UninstallDelete]
; Remove app config from %APPDATA% only if user chose to (see Code section)
Type: dirifempty; Name: "{userappdata}\{#MyAppName}"


; ============================================================================
;  Pascal Script — helper functions
; ============================================================================
[Code]

var
  BrandLogo: TBitmapImage;
  BrandWW, BrandR, BrandRest: TNewStaticText;

procedure AddInstallerBranding();
var
  LeftEdge, TopEdge, TotalWidth: Integer;
begin
  { Native controls keep the established app icon and exact red-R spelling. }
  BrandLogo := TBitmapImage.Create(WizardForm);
  BrandLogo.Parent := WizardForm.WelcomePage;
  BrandLogo.PngImage.Assign(WizardForm.WizardSmallBitmapImage.PngImage);
  BrandLogo.Stretch := True;
  BrandLogo.AutoSize := False;
  BrandLogo.Width := ScaleX(64);
  BrandLogo.Height := ScaleY(64);
  BrandLogo.Left := (WizardForm.WizardBitmapImage.Width - BrandLogo.Width) div 2;
  BrandLogo.Top := ScaleY(62);
  BrandWW := TNewStaticText.Create(WizardForm);
  BrandR := TNewStaticText.Create(WizardForm);
  BrandRest := TNewStaticText.Create(WizardForm);
  BrandWW.Parent := WizardForm.WelcomePage;
  BrandR.Parent := WizardForm.WelcomePage;
  BrandRest.Parent := WizardForm.WelcomePage;
  BrandWW.Caption := 'WW';
  BrandR.Caption := 'R';
  BrandRest.Caption := 'ecorder';
  BrandWW.Font.Name := 'Segoe UI';
  BrandWW.Font.Size := 16;
  BrandWW.Font.Style := [fsBold];
  BrandWW.Font.Color := $F5F2F0;
  BrandR.Font.Assign(BrandWW.Font);
  BrandR.Font.Color := $5540FF;
  BrandRest.Font.Assign(BrandWW.Font);
  BrandWW.Color := $1D1511;
  BrandR.Color := $1D1511;
  BrandRest.Color := $1D1511;
  BrandWW.AutoSize := True;
  BrandR.AutoSize := True;
  BrandRest.AutoSize := True;
  TotalWidth := BrandWW.Width + BrandR.Width + BrandRest.Width;
  LeftEdge := (WizardForm.WizardBitmapImage.Width - TotalWidth) div 2;
  TopEdge := BrandLogo.Top + BrandLogo.Height + ScaleY(16);
  BrandWW.Left := LeftEdge;
  BrandWW.Top := TopEdge;
  BrandR.Left := BrandWW.Left + BrandWW.Width;
  BrandR.Top := TopEdge;
  BrandRest.Left := BrandR.Left + BrandR.Width;
  BrandRest.Top := TopEdge;
end;

procedure InitializeWizard();
begin
  AddInstallerBranding();
  { Keep complete glyph bounds at fractional DPI, with comfortable line spacing. }
  WizardForm.TasksList.MinItemHeight := ScaleY(26);
  WizardForm.TasksList.Offset := ScaleX(8);
  WizardForm.ComponentsList.MinItemHeight := ScaleY(26);
  WizardForm.ComponentsList.Offset := ScaleX(8);
  WizardForm.RunList.MinItemHeight := ScaleY(26);
  WizardForm.RunList.Offset := ScaleX(8);
  WizardForm.ReadyLabel.Caption := 'Ready to install WWRecorder';
end;

// ── Check whether the app is currently running ─────────────────────────────
function IsAppRunning(): Boolean;
begin
  Result := CheckForMutexes('{#MyAppMutex}');
end;

// ── Pre-install: warn if already running ──────────────────────────────────
function InitializeSetup(): Boolean;
var
  Attempt: Integer;
begin
  { In-app update launches Setup just before quitting. Give that idle shutdown
    time to release the same session mutex, without force-killing capture. }
  for Attempt := 1 to 60 do
  begin
    if not IsAppRunning() then Break;
    Sleep(100);
  end;
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

// Never force-kill an application that might own unfinished media.
function InitializeUninstall(): Boolean;
begin
  Result := not IsAppRunning();
  if (not Result) and (not UninstallSilent) then
    MsgBox('Please finish or discard any recording/export and quit WWRecorder, then run uninstall again.' + #13#10 +
      'Your recordings have not been changed.', mbInformation, MB_OK);
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
