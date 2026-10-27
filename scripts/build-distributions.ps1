[CmdletBinding()]
param(
    [ValidateSet('Both','Msix','Exe')][string]$Format = 'Both',
    [string]$IdentityFile = 'packaging/msix/test-identity.json',
    [string]$PackageVersion = '',
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
$originalPath = $env:PATH
try {
    $pythonExe = (Get-Command python.exe).Source
    $pythonRoot = Split-Path $pythonExe
    $env:PATH = "$pythonRoot;$pythonRoot\Scripts;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
    $version = (& $pythonExe -c 'import ast; t=ast.parse(open("app/main.py", encoding="utf-8-sig").read()); print(next(ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=="APP_VERSION" for x in n.targets)))').Trim()
    if ($LASTEXITCODE) { throw 'Cannot read app version' }
    $artifactVersion = $version
    if ($PackageVersion) { $artifactVersion = $PackageVersion } else { $PackageVersion = "$version.0" }
    $payload = Join-Path $repoRoot 'work\payloads\dual\WWRecorder'
    if (-not $SkipBuild) {
        & $pythonExe -m PyInstaller --clean --noconfirm --distpath work/payloads/dual --workpath work/build/dual packaging/shared/wwrecorder.spec
        if ($LASTEXITCODE) { throw 'PyInstaller build failed' }
    }
    $badDlls = Get-ChildItem -LiteralPath $payload -Recurse -File | Where-Object { $_.Name -match '^(icuuc|icudt.*|ucrtbase|api-ms-win-.*)\.dll$' }
    if ($badDlls) { throw "Forbidden runtime DLLs in payload: $($badDlls.Name -join ', ')" }
    $identity = Get-Content -LiteralPath $IdentityFile -Raw | ConvertFrom-Json
    $output = Join-Path $repoRoot "artifacts\windows\$artifactVersion\$($identity.channel)"
    $exeOutput = Join-Path $output 'exe'
    $msixOutput = Join-Path $output 'msix'
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    if ($Format -in @('Both','Msix')) {
        New-Item -ItemType Directory -Path $msixOutput -Force | Out-Null
        $sdkRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        $sdk = Get-ChildItem -LiteralPath $sdkRoot -Directory | Where-Object { $_.Name -match '^10\.' -and (Test-Path (Join-Path $_.FullName 'x64\makeappx.exe')) } | Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
        if (-not $sdk) { throw 'Install Windows SDK with MakeAppx and SignTool first.' }
        $stage = Join-Path $repoRoot ('work\build\msix-' + [guid]::NewGuid().ToString('N'))
        & $pythonExe packaging/msix/stage_msix.py --payload $payload --stage $stage --identity $IdentityFile --version $PackageVersion
        if ($LASTEXITCODE) { throw 'MSIX staging failed' }
        $makepri = Join-Path $sdk.FullName 'x64\makepri.exe'
        if (-not (Test-Path $makepri)) { throw 'Windows SDK MakePRI is required for unplated taskbar icons.' }
        $priConfig = Join-Path $repoRoot ('work\build\pri-' + [guid]::NewGuid().ToString('N') + '.xml')
        & $makepri createconfig /cf $priConfig /dq lang-en-US /o
        if ($LASTEXITCODE) { throw 'MakePRI configuration failed' }
        & $makepri new /pr $stage /cf $priConfig /mn (Join-Path $stage 'AppxManifest.xml') /of (Join-Path $stage 'resources.pri') /o
        if ($LASTEXITCODE) { throw 'MakePRI taskbar icon indexing failed' }
        $priDump = $priConfig + '.dump.xml'
        & $makepri dump /if (Join-Path $stage 'resources.pri') /of $priDump /o
        if ($LASTEXITCODE) { throw 'MakePRI verification dump failed' }
        $indexedResources = Get-Content -LiteralPath $priDump -Raw
        if ($indexedResources -notmatch 'altform-unplated' -or $indexedResources -notmatch 'altform-lightunplated') {
            throw 'Taskbar icon variants were not indexed by MakePRI'
        }
        $package = Join-Path $msixOutput "WWRecorder_$($artifactVersion)_x64_$($identity.channel).msix"
        & (Join-Path $sdk.FullName 'x64\makeappx.exe') pack /d $stage /p $package /o
        if ($LASTEXITCODE) { throw 'MakeAppx validation/packaging failed' }
        if ($identity.channel -eq 'local-test') {
            $certificate = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq $identity.publisher -and $_.NotAfter -gt (Get-Date).AddDays(7) -and $_.HasPrivateKey } | Sort-Object NotAfter -Descending | Select-Object -First 1
            if (-not $certificate) {
                $certificate = New-SelfSignedCertificate -Type Custom -Subject $identity.publisher -FriendlyName 'WWRecorder local MSIX testing only' -KeyUsage DigitalSignature -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 -KeyExportPolicy NonExportable -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(1) -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3','2.5.29.19={text}')
            }
            & (Join-Path $sdk.FullName 'x64\signtool.exe') sign /fd SHA256 /sha1 $certificate.Thumbprint /s My $package
            if ($LASTEXITCODE) { throw 'MSIX test signing failed' }
            Export-Certificate -Cert $certificate -FilePath (Join-Path $msixOutput 'WWRecorder-Test.cer') -Force | Out-Null
            Copy-Item -LiteralPath packaging/msix/Install-Test.ps1 -Destination $msixOutput
            Copy-Item -LiteralPath packaging/msix/Install-Test.cmd -Destination $msixOutput
            Copy-Item -LiteralPath packaging/msix/TESTING.md -Destination $msixOutput
            $signer = Get-AuthenticodeSignature -LiteralPath $package
            if ($signer.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) { throw 'Package signer does not match test certificate' }
        }
    }
    if ($Format -in @('Both','Exe')) {
        New-Item -ItemType Directory -Path $exeOutput -Force | Out-Null
        $iscc = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
        & $iscc "/DDistDir=$payload" "/O$exeOutput" "/FWWRecorder_Setup_$($artifactVersion)_$($identity.channel)" packaging/exe/installer_config.iss
        if ($LASTEXITCODE) { throw 'EXE installer build failed' }
    }
    Get-ChildItem -LiteralPath $output -Recurse -File | Where-Object { $_.Extension -in @('.exe','.msix','.cer') } | Get-FileHash -Algorithm SHA256 | Select-Object @{n='file';e={$_.Path.Substring($output.Length + 1).Replace('\', '/')}},Hash | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'SHA256.json') -Encoding UTF8
    Write-Host "Artifacts: $output"
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
